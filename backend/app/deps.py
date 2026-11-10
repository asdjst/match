from fastapi import Request

from infra.config import Settings


def settings(request: Request) -> Settings:
    return request.app.state.settings


def graph(request: Request):
    return request.app.state.graph


def runs(request: Request) -> dict:
    return request.app.state.runs
