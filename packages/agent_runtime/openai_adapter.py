"""Small, bounded Responses API adapter for AgentForge workers."""

from dataclasses import dataclass

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field


class GeneratedFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    content: str


class GeneratedProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str
    files: list[GeneratedFile] = Field(min_length=1, max_length=30)


@dataclass(frozen=True)
class ModelResult:
    text: str
    input_tokens: int
    output_tokens: int


def generate_text(instructions: str, prompt: str, model: str) -> ModelResult:
    client = OpenAI(timeout=120.0, max_retries=2)
    response = client.responses.create(
        model=model,
        instructions=instructions,
        input=prompt,
        store=False,
        max_output_tokens=4000,
    )
    if response.status != "completed" or not response.output_text:
        raise RuntimeError("Model response was empty or incomplete")
    return ModelResult(
        text=response.output_text,
        input_tokens=response.usage.input_tokens if response.usage else 0,
        output_tokens=response.usage.output_tokens if response.usage else 0,
    )


def generate_project(prompt: str, model: str) -> tuple[GeneratedProject, ModelResult]:
    instructions = (
        "You are a software developer. Build a small, runnable Python 3.13 project for "
        "the supplied requirement and design. Return complete file contents. "
        "Use Python standard library only, include README.md and unittest tests. "
        "Do not include secrets, deployment commands, shell scripts, or binary files. "
        "Keep total output small enough for a single reviewable change."
    )
    client = OpenAI(timeout=180.0, max_retries=2)
    response = client.responses.parse(
        model=model,
        instructions=instructions,
        input=prompt,
        text_format=GeneratedProject,
        store=False,
        max_output_tokens=12000,
    )
    project = response.output_parsed
    if response.status != "completed" or project is None:
        raise RuntimeError("Model did not return a complete project manifest")
    return project, ModelResult(
        text=project.summary,
        input_tokens=response.usage.input_tokens if response.usage else 0,
        output_tokens=response.usage.output_tokens if response.usage else 0,
    )
