"""Semantic layer: loads semantic/metrics.yml and compiles metric queries to SQL.

This is the only path from the API, alerts and the Q&A agent to the warehouse.
Callers describe *what* they want (metrics, dimensions, grain, filters); identifiers
are validated against the YAML whitelist and every value is a bound parameter, so no
caller-supplied text is ever interpolated into SQL.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import duckdb
import yaml
from pydantic import BaseModel, Field, field_validator

GRAINS = ("day", "week", "month", "quarter", "year")
Grain = Literal["day", "week", "month", "quarter", "year"]
FilterOp = Literal["eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte"]
Scalar = str | int | float | bool | date

_OPS_SQL = {"eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
_IDENT = re.compile(r"^[a-z][a-z0-9_]*$")
_REF = re.compile(r"\{([a-z][a-z0-9_]*)\}")
_DERIVED_ALLOWED = re.compile(r"^[\s0-9.+\-*/(),]*$")
_DERIVED_FUNCS = {"least", "greatest", "nullif", "coalesce", "abs"}
DEFAULT_ATTRIBUTION = "position_based"


class SemanticError(ValueError):
    """Invalid metric definition or query. Messages are safe to show to users."""


# --- definitions --------------------------------------------------------------------


@dataclass(frozen=True)
class Dimension:
    name: str
    type: Literal["string", "date", "integer", "boolean"]
    label: str
    description: str
    values: tuple[str, ...] = ()


@dataclass(frozen=True)
class Measure:
    name: str
    agg: Literal["sum", "min", "max", "count"]
    expr: str
    description: str
    model: str


@dataclass(frozen=True)
class SemanticModel:
    name: str
    table: str
    description: str
    time_dimension: str
    min_grain: str
    dimensions: tuple[str, ...]
    measures: dict[str, Measure]


@dataclass(frozen=True)
class Filter:
    dimension: str
    op: FilterOp
    value: Any


@dataclass(frozen=True)
class MetricInput:
    measure: str
    filters: tuple[Filter, ...] = ()
    offset_months: int = 0


@dataclass(frozen=True)
class Metric:
    name: str
    label: str
    type: Literal["simple", "ratio", "derived"]
    description: str
    formula: str
    format: str
    measure: MetricInput | None = None
    numerator: MetricInput | None = None
    denominator: MetricInput | None = None
    expr: str | None = None
    depends_on: tuple[str, ...] = ()
    fully_loaded_variant: str | None = None


# --- queries ------------------------------------------------------------------------


class QueryFilter(BaseModel):
    dimension: str
    op: FilterOp = "eq"
    value: Scalar | list[Scalar]


class OrderBy(BaseModel):
    field: str
    descending: bool = False


class MetricQuery(BaseModel):
    metrics: list[str] = Field(min_length=1, max_length=16)
    dimensions: list[str] = Field(default_factory=list, max_length=4)
    grain: Grain | None = None
    start: date | None = None
    end: date | None = None
    filters: list[QueryFilter] = Field(default_factory=list, max_length=12)
    attribution_model: str = DEFAULT_ATTRIBUTION
    order_by: list[OrderBy] = Field(default_factory=list, max_length=4)
    limit: int | None = Field(default=None, ge=1, le=10_000)

    @field_validator("metrics", "dimensions")
    @classmethod
    def _no_duplicates(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("duplicate entries are not allowed")
        return value


@dataclass
class CompiledQuery:
    sql: str
    params: list[Any]
    columns: list[str]
    metrics: list[str]
    dimensions: list[str]
    grain: str | None

    def display_sql(self) -> str:
        """SQL with parameters inlined, for query transparency in the UI only."""
        parts = self.sql.split("?")
        out = [parts[0]]
        for value, rest in zip(self.params, parts[1:], strict=True):
            out.append(_literal(value) + rest)
        return "".join(out)


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    sql: str
    query: dict[str, Any] = field(default_factory=dict)


def _literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, date):
        return f"DATE '{value.isoformat()}'"
    return "'" + str(value).replace("'", "''") + "'"


# --- loading ------------------------------------------------------------------------


def _parse_input(raw: Any, metric: str) -> MetricInput:
    if isinstance(raw, str):
        return MetricInput(measure=raw)
    if not isinstance(raw, dict) or "measure" not in raw:
        raise SemanticError(f"metric {metric}: inputs need a measure")
    filters = tuple(
        Filter(f["dimension"], f.get("op", "eq"), f["value"]) for f in raw.get("filters", [])
    )
    return MetricInput(
        measure=raw["measure"], filters=filters, offset_months=int(raw.get("offset_months", 0))
    )


class SemanticLayer:
    def __init__(
        self,
        models: dict[str, SemanticModel],
        dimensions: dict[str, Dimension],
        metrics: dict[str, Metric],
    ) -> None:
        self.models = models
        self.dimensions = dimensions
        self.metrics = metrics
        self.measures: dict[str, Measure] = {}
        for model in models.values():
            for name, measure in model.measures.items():
                if name in self.measures:
                    raise SemanticError(f"measure {name} is defined in two semantic models")
                self.measures[name] = measure
        self._validate()

    @classmethod
    def from_yaml(cls, path: Path) -> SemanticLayer:
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        dimensions = {
            name: Dimension(
                name=name,
                type=d.get("type", "string"),
                label=d.get("label", name),
                description=d.get("description", ""),
                values=tuple(d.get("values", [])),
            )
            for name, d in spec["dimensions"].items()
        }
        models: dict[str, SemanticModel] = {}
        for m in spec["semantic_models"]:
            measures = {
                name: Measure(
                    name=name,
                    agg=ms.get("agg", "sum"),
                    expr=ms.get("expr", name),
                    description=ms.get("description", ""),
                    model=m["name"],
                )
                for name, ms in m["measures"].items()
            }
            models[m["name"]] = SemanticModel(
                name=m["name"],
                table=m["table"],
                description=m.get("description", ""),
                time_dimension=m["time_dimension"],
                min_grain=m.get("min_grain", "day"),
                dimensions=tuple(m["dimensions"]),
                measures=measures,
            )
        metrics: dict[str, Metric] = {}
        for name, raw in spec["metrics"].items():
            kind = raw["type"]
            expr = raw.get("expr")
            metrics[name] = Metric(
                name=name,
                label=raw.get("label", name),
                type=kind,
                description=raw.get("description", ""),
                formula=raw.get("formula", ""),
                format=raw.get("format", "number"),
                measure=_parse_input(raw["measure"], name) if kind == "simple" else None,
                numerator=_parse_input(raw["numerator"], name) if kind == "ratio" else None,
                denominator=_parse_input(raw["denominator"], name) if kind == "ratio" else None,
                expr=expr,
                depends_on=tuple(_REF.findall(expr)) if expr else (),
                fully_loaded_variant=raw.get("fully_loaded_variant"),
            )
        return cls(models, dimensions, metrics)

    # -- validation --------------------------------------------------------------------
    def _validate(self) -> None:
        for model in self.models.values():
            for ident in (model.time_dimension, *model.dimensions, *model.measures):
                if not _IDENT.match(ident):
                    raise SemanticError(f"invalid identifier {ident!r} in {model.name}")
            if not re.match(r"^[a-z_]+\.[a-z_]+$", model.table):
                raise SemanticError(f"invalid table {model.table!r}")
            for dim in model.dimensions:
                if dim not in self.dimensions:
                    raise SemanticError(f"{model.name} uses undeclared dimension {dim}")
        for metric in self.metrics.values():
            if not _IDENT.match(metric.name):
                raise SemanticError(f"invalid metric name {metric.name!r}")
            for inp in self._direct_inputs(metric):
                if inp.measure not in self.measures:
                    raise SemanticError(f"metric {metric.name} uses unknown measure {inp.measure}")
                for f in inp.filters:
                    self._check_filter_dimension(f.dimension)
            if metric.type == "derived":
                self._validate_expr(metric)
            variant = metric.fully_loaded_variant
            if variant and variant not in self.metrics:
                raise SemanticError(f"metric {metric.name} has unknown variant {variant}")
        for name in self.metrics:
            self._resolve_inputs(name, ())

    def _validate_expr(self, metric: Metric) -> None:
        assert metric.expr is not None
        for ref in metric.depends_on:
            if ref not in self.metrics:
                raise SemanticError(f"metric {metric.name} references unknown metric {ref}")
        stripped = _REF.sub("0", metric.expr)
        stripped = re.sub(r"[a-z_]+(?=\s*\()", lambda m: "" if m.group(0) in _DERIVED_FUNCS
                          else "!", stripped)
        if not _DERIVED_ALLOWED.match(stripped):
            raise SemanticError(f"metric {metric.name} has an unsupported expression")

    def _check_filter_dimension(self, dimension: str) -> Dimension:
        if dimension not in self.dimensions:
            raise SemanticError(f"unknown dimension '{dimension}'")
        return self.dimensions[dimension]

    @staticmethod
    def _direct_inputs(metric: Metric) -> list[MetricInput]:
        return [i for i in (metric.measure, metric.numerator, metric.denominator) if i]

    def _resolve_inputs(self, name: str, stack: tuple[str, ...]) -> list[MetricInput]:
        if name in stack:
            raise SemanticError(f"metric cycle: {' -> '.join((*stack, name))}")
        metric = self.metrics[name]
        if metric.type != "derived":
            return self._direct_inputs(metric)
        inputs: list[MetricInput] = []
        for dep in metric.depends_on:
            inputs.extend(self._resolve_inputs(dep, (*stack, name)))
        return inputs

    # -- public helpers ----------------------------------------------------------------
    def metric(self, name: str) -> Metric:
        if name not in self.metrics:
            raise SemanticError(f"unknown metric '{name}'")
        return self.metrics[name]

    def variant(self, name: str, fully_loaded: bool) -> str:
        """The metric the "fully loaded" toggle maps `name` to (itself if none)."""
        metric = self.metric(name)
        return (metric.fully_loaded_variant or name) if fully_loaded else name

    def models_for_metric(self, name: str) -> list[SemanticModel]:
        names = {self.measures[i.measure].model for i in self._resolve_inputs(name, ())}
        return [self.models[n] for n in sorted(names)]

    def metric_dimensions(self, name: str) -> list[str]:
        """Dimensions every semantic model behind the metric can be grouped by."""
        models = self.models_for_metric(name)
        common = set(models[0].dimensions)
        for model in models[1:]:
            common &= set(model.dimensions)
        return [d for d in self.dimensions if d in common]

    def metric_min_grain(self, name: str) -> str:
        return max((m.min_grain for m in self.models_for_metric(name)), key=GRAINS.index)

    def catalog(self) -> dict[str, Any]:
        return {
            "metrics": [
                {
                    "name": m.name,
                    "label": m.label,
                    "type": m.type,
                    "description": m.description,
                    "formula": m.formula,
                    "format": m.format,
                    "dimensions": self.metric_dimensions(m.name),
                    "min_grain": self.metric_min_grain(m.name),
                    "fully_loaded_variant": m.fully_loaded_variant,
                }
                for m in self.metrics.values()
            ],
            "dimensions": [
                {
                    "name": d.name,
                    "label": d.label,
                    "type": d.type,
                    "description": d.description,
                    "values": list(d.values),
                }
                for d in self.dimensions.values()
            ],
            "grains": list(GRAINS),
        }

    # -- compilation -------------------------------------------------------------------
    def _coerce(self, dim: Dimension, value: Any) -> Any:
        try:
            if dim.type == "boolean":
                if isinstance(value, str):
                    if value.lower() not in {"true", "false", "1", "0"}:
                        raise ValueError
                    return value.lower() in {"true", "1"}
                return bool(value)
            if dim.type == "integer":
                return int(value)
            if dim.type == "date":
                return value if isinstance(value, date) else date.fromisoformat(str(value))
        except (TypeError, ValueError) as exc:
            raise SemanticError(f"invalid value {value!r} for {dim.name}") from exc
        text = str(value)
        if dim.values and text not in dim.values:
            allowed = ", ".join(dim.values)
            raise SemanticError(f"invalid value '{text}' for {dim.name} (allowed: {allowed})")
        return text

    def _filter_sql(self, f: Filter, params: list[Any]) -> str:
        dim = self._check_filter_dimension(f.dimension)
        if f.op in ("in", "not_in"):
            values = f.value if isinstance(f.value, list | tuple) else [f.value]
            if not values:
                raise SemanticError(f"filter on {f.dimension} needs at least one value")
            params.extend(self._coerce(dim, v) for v in values)
            placeholders = ", ".join("?" for _ in values)
            return f"{dim.name} {'not in' if f.op == 'not_in' else 'in'} ({placeholders})"
        if isinstance(f.value, list | tuple):
            raise SemanticError(f"operator {f.op} on {f.dimension} takes a single value")
        params.append(self._coerce(dim, f.value))
        return f"{dim.name} {_OPS_SQL[f.op]} ?"

    def compile(self, query: MetricQuery) -> CompiledQuery:
        metrics = [self.metric(name) for name in query.metrics]
        for dim in query.dimensions:
            self._check_filter_dimension(dim)
        if query.start and query.end and query.start > query.end:
            raise SemanticError("start must be on or before end")

        filters = [Filter(f.dimension, f.op, f.value) for f in query.filters]
        model_filtered = any(f.dimension == "attribution_model" for f in filters)
        if "attribution_model" not in query.dimensions and not model_filtered:
            filters.append(Filter("attribution_model", "eq", query.attribution_model))

        # Unique measure inputs across all requested metrics (derived ones resolved).
        inputs: list[MetricInput] = []
        for metric in metrics:
            for inp in self._resolve_inputs(metric.name, ()):
                if inp not in inputs:
                    inputs.append(inp)
        aliases = {inp: f"m{i}" for i, inp in enumerate(inputs)}

        # One CTE per (semantic model, input filters, offset).
        groups: dict[tuple[str, tuple[Filter, ...], int], list[MetricInput]] = {}
        for inp in inputs:
            key = (self.measures[inp.measure].model, inp.filters, inp.offset_months)
            groups.setdefault(key, []).append(inp)

        keys = (["period"] if query.grain else []) + list(query.dimensions)
        params: list[Any] = []
        ctes: list[str] = []
        for idx, ((model_name, input_filters, offset), group) in enumerate(groups.items()):
            model = self.models[model_name]
            needed = set(query.dimensions) | {f.dimension for f in (*filters, *input_filters)}
            missing = sorted(needed - set(model.dimensions))
            if missing:
                names = ", ".join(m.name for m in metrics)
                raise SemanticError(
                    f"dimension(s) {', '.join(missing)} not available for {names}"
                )
            if query.grain and GRAINS.index(query.grain) < GRAINS.index(model.min_grain):
                raise SemanticError(
                    f"grain '{query.grain}' is finer than {model.name} data "
                    f"(minimum '{model.min_grain}')"
                )
            time_expr = model.time_dimension
            if offset:
                time_expr = f"cast({time_expr} + interval {int(offset)} month as date)"
            select: list[str] = []
            if query.grain:
                select.append(f"cast(date_trunc('{query.grain}', {time_expr}) as date) as period")
            select.extend(query.dimensions)
            select.extend(
                f"{self.measures[i.measure].agg}({self.measures[i.measure].expr}) as {aliases[i]}"
                for i in group
            )
            where: list[str] = []
            if query.start:
                where.append(
                    f"{time_expr} >= cast(date_trunc('{model.min_grain}', cast(? as date)) as date)"
                )
                params.append(query.start)
            if query.end:
                where.append(f"{time_expr} <= cast(? as date)")
                params.append(query.end)
            where.extend(self._filter_sql(f, params) for f in (*filters, *input_filters))
            sql = f"cte{idx} as (\n  select {', '.join(select)}\n  from {model.table}"
            if where:
                sql += "\n  where " + "\n    and ".join(where)
            if keys:
                sql += "\n  group by all"
            ctes.append(sql + "\n)")

        exprs = {m.name: self._metric_expr(m.name, aliases) for m in metrics}
        select_cols = [*keys, *(f'{exprs[m.name]} as "{m.name}"' for m in metrics)]
        from_sql = "cte0"
        for idx in range(1, len(ctes)):
            from_sql += (
                f"\nfull outer join cte{idx} using ({', '.join(keys)})"
                if keys
                else f"\ncross join cte{idx}"
            )
        sql = "with " + ",\n".join(ctes) + f"\nselect {', '.join(select_cols)}\nfrom {from_sql}"

        order_terms: list[str] = []
        valid_order = set(keys) | {m.name for m in metrics}
        for ob in query.order_by:
            if ob.field not in valid_order:
                raise SemanticError(f"cannot order by '{ob.field}'")
            col = f'"{ob.field}"' if ob.field in exprs else ob.field
            order_terms.append(f"{col} {'desc' if ob.descending else 'asc'} nulls last")
        order_terms.extend(k for k in keys if k not in {o.field for o in query.order_by})
        if order_terms:
            sql += "\norder by " + ", ".join(order_terms)
        if query.limit:
            sql += f"\nlimit {int(query.limit)}"
        return CompiledQuery(
            sql=sql,
            params=params,
            columns=[*keys, *query.metrics],
            metrics=list(query.metrics),
            dimensions=list(query.dimensions),
            grain=query.grain,
        )

    def _input_expr(self, inp: MetricInput, aliases: dict[MetricInput, str]) -> str:
        return f"coalesce({aliases[inp]}, 0)"

    def _metric_expr(self, name: str, aliases: dict[MetricInput, str]) -> str:
        metric = self.metrics[name]
        if metric.type == "simple":
            assert metric.measure is not None
            return self._input_expr(metric.measure, aliases)
        if metric.type == "ratio":
            assert metric.numerator is not None and metric.denominator is not None
            num = self._input_expr(metric.numerator, aliases)
            den = self._input_expr(metric.denominator, aliases)
            return f"(cast({num} as double) / nullif({den}, 0))"
        assert metric.expr is not None
        return "(" + _REF.sub(
            lambda m: self._metric_expr(m.group(1), aliases), metric.expr
        ) + ")"

    # -- execution ---------------------------------------------------------------------
    def query(self, conn: duckdb.DuckDBPyConnection, query: MetricQuery) -> QueryResult:
        compiled = self.compile(query)
        cursor = conn.execute(compiled.sql, compiled.params)
        names = [d[0] for d in cursor.description]
        rows = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
        for row in rows:
            for key, value in row.items():
                if isinstance(value, float) and value != value:  # NaN -> null
                    row[key] = None
        return QueryResult(
            columns=compiled.columns,
            rows=rows,
            sql=compiled.display_sql(),
            query=query.model_dump(mode="json", exclude_defaults=True),
        )


@lru_cache(maxsize=4)
def load_semantic_layer(path: Path) -> SemanticLayer:
    return SemanticLayer.from_yaml(path)
