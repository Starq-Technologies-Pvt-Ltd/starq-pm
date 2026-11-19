"""starq-pm — software project management for Hermes agent floors.
Native general plugin: plugin.yaml + register(ctx), called once at startup.
Zero capabilities, zero python dependencies, zero hooks/daemons."""
from .operations import PM
from .tools import TOOLS, make_handler
from .cli import setup_cli, cli_handler, slash_handler

_PM_INSTANCE = None


def register(ctx):
    from plugins.plugin_storage import plugin_data_dir  # public API

    settings = {}
    for key in ("roles", "tolerances", "risk_criteria", "quality_profiles", "dod_profiles",
                "wip", "cadence", "autonomy", "evidence_max_age", "estimation", "rework_max_cycles",
                "stages", "dow", "blocker_age_threshold_s"):
        val = ctx.get_config(key)
        if val is not None:
            settings[key] = val

    pm = PM(
        plugin_data_dir("starq-pm"),
        settings=settings,
        plugin_probe=ctx.has_plugin,                      # seam probes
        redactor=lambda t: ctx.redact_text(t, force=True),  # export hygiene
    )
    global _PM_INSTANCE
    _PM_INSTANCE = pm  # test/lifecycle hook: explicit store close (warning-clean)

    for name, spec in TOOLS.items():
        ctx.register_tool(name=name, toolset="starq-pm", schema=spec["schema"],
                          handler=make_handler(pm, name))  #

    ctx.register_cli_command(
        "starq-pm", "StarqPM project management (board, reports, chain audit)",
        lambda parser: setup_cli(parser, pm),
        handler_fn=lambda args: cli_handler(args, pm),
    )  #

    ctx.register_command(
        "starq-pm", lambda raw: slash_handler(pm, raw),
        description="StarqPM: board / report / chain_verify / <action> {json}",
        args_hint="<action> [json]",
    )  #
