"""starq-pm CLI + slash surfaces. Read-heavy ops work without a model turn.
hermes starq-pm <action> --occupant ID [--args JSON] [--project ID]
/starq-pm <action> [JSON args] (occupant from configured default or JSON)"""
import json


def setup_cli(parser, pm):
    parser.add_argument("action", help="action name (e.g. board, chain_verify, metrics_compute, config_show)")
    parser.add_argument("--occupant", required=True, help="configured occupant id")
    parser.add_argument("--args", default="{}", help="JSON action arguments")
    parser.add_argument("--project", default=None, help="project id shorthand")


def cli_handler(args, pm):
    try:
        inner = json.loads(args.args)
    except json.JSONDecodeError as exc:
        return json.dumps({"error": "F-11", "reason": f"invalid --args JSON: {exc}"})
    if args.project:
        inner.setdefault("project_id", args.project)
    result = json.dumps(pm.operate(args.action, inner, args.occupant))
    print(result)  # host CLI dispatcher discards handler return values; print for readable output
    return result


def slash_handler(pm, raw_args):
    raw_args = (raw_args or "").strip()
    if not raw_args:
        return json.dumps(pm.operate("board", {}, _default_occupant(pm)))
    parts = raw_args.split(None, 1)
    action = parts[0]
    inner = {}
    if len(parts) > 1:
        try:
            inner = json.loads(parts[1])
        except json.JSONDecodeError:
            return json.dumps({"error": "F-11", "reason": "args must be JSON"})
    occupant = inner.pop("occupant", None) or _default_occupant(pm)
    return json.dumps(pm.operate(action, inner, occupant))


def _default_occupant(pm):
    for role in ("O", "F", "E", "V"):
        occ = pm.gov.settings["roles"].get(role, {}).get("occupants", [])
        if occ:
            return occ[0]
    return ""
