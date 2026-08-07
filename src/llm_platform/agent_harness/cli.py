import os
import uuid
from pathlib import Path

import typer

from llm_platform.agent_harness.state import AgentTaskState, TaskStateStore
from llm_platform.agent_harness.workspace import SafeWorkspace

app = typer.Typer(help="Per-user coding-agent harness (initial safe capability subset)")


def default_state_dir() -> Path:
    return Path.home() / ".local" / "share" / "agent-harness" / "tasks"


@app.callback(invoke_without_command=True)
def start(
    ctx: typer.Context,
    request: str = typer.Option("", "--request"),
    policy: str = typer.Option("balanced", "--policy"),
    prefer_model: str | None = typer.Option(None, "--prefer-model"),
    force_model: str | None = typer.Option(None, "--force-model"),
    force_runtime: str | None = typer.Option(None, "--force-runtime"),
    force_deployment: str | None = typer.Option(None, "--force-deployment"),
    max_wait: int = typer.Option(300, "--max-wait", min=1),
    resume: str | None = typer.Option(None, "--resume"),
    in_place: bool = typer.Option(False, "--in-place"),
) -> None:
    del max_wait
    if ctx.invoked_subcommand is not None:
        return
    store = TaskStateStore(default_state_dir())
    if resume is not None:
        state = store.load(resume)
        typer.echo(f"resumed {state.task_id}: phase={state.phase.value} model={state.model}")
        return
    if not request:
        raise typer.BadParameter("--request is required when starting a task")
    workspace = SafeWorkspace(Path.cwd(), allow_in_place=in_place)
    del workspace
    model = f"auto/{policy}"
    runtime = None
    deployment = None
    if prefer_model:
        model = f"prefer/{prefer_model}"
    if force_model:
        model = f"force/{force_model}"
    if force_runtime:
        runtime = force_runtime
        if force_model:
            model = f"force/{force_model}@{force_runtime}"
    if force_deployment:
        deployment = force_deployment
        model = f"force-deployment/{force_deployment}"
    state = AgentTaskState(
        task_id=f"task-{uuid.uuid4().hex}",
        repository=str(Path.cwd().resolve()),
        user_request=request,
        model=model,
        runtime=runtime,
        deployment=deployment,
    )
    store.save(state)
    typer.echo(f"created {state.task_id}: phase=discover model={state.model}")
    if "LOCAL_LLM_GATEWAY_API_KEY" not in os.environ:
        typer.echo("gateway key is not set; task state was saved but inference was not attempted")


@app.command()
def status(task_id: str) -> None:
    state = TaskStateStore(default_state_dir()).load(task_id)
    typer.echo(f"{state.task_id} {state.status} phase={state.phase.value} model={state.model}")


if __name__ == "__main__":
    app()
