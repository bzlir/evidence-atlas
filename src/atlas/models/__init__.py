from __future__ import annotations

from pydantic import BaseModel, Field


class ParamOption(BaseModel):
    value: str
    label: str = ""
    default: bool = False


class Param(BaseModel):
    id: str
    name: str
    type: str
    options: list[ParamOption] = []
    required: bool = False
    default: str | None = None
    project_id: str = ""


class Query(BaseModel):
    id: str
    compiled_sql: str
    input_sql: str
    inline: bool
    compiled: bool = False
    compile_error: str | None = None
    project_id: str = ""


class Dataset(BaseModel):
    id: str
    component_type: str
    bound_query: str
    where_template: str | None = None
    page_id: str = ""
    partial: str = ""
    ordinal: int = 0
    attrs: dict[str, str] = {}
    project_id: str = ""
    resolvable: bool = False


class Page(BaseModel):
    id: str
    route: str
    project_id: str = ""


class Project(BaseModel):
    id: str
    name: str
    path: str


class Relation(BaseModel):
    from_: str = Field(alias="from")
    to: str
    type: str

    model_config = {"populate_by_name": True}
