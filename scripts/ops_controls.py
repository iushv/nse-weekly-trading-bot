from __future__ import annotations

import argparse

from trading_bot.monitoring.ops_controls import (
    build_notify_template,
    clear_kill_switch,
    create_incident_note,
    is_kill_switch_active,
    set_kill_switch,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operational control helpers (kill switch, incident notes, templates).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    kill = sub.add_parser("kill-switch", help="Manage kill switch flag.")
    kill.add_argument("action", choices=["on", "off", "status"])
    kill.add_argument("--control-dir", default="control")
    kill.add_argument("--reason", default="manual")

    incident = sub.add_parser("incident-note", help="Create incident markdown note.")
    incident.add_argument("--title", required=True)
    incident.add_argument("--severity", default="medium")
    incident.add_argument("--details", required=True)
    incident.add_argument("--actions", default="")
    incident.add_argument("--output-dir", default="reports/incidents")

    notify = sub.add_parser("notify-template", help="Print incident notification template.")
    notify.add_argument("--kind", choices=["broker_outage", "data_gap", "alerts_down"], required=True)
    notify.add_argument("--context", default="")

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.cmd == "kill-switch":
        if args.action == "on":
            path = set_kill_switch(control_dir=args.control_dir, reason=args.reason)
            print(f"Kill switch enabled: {path}")
            return 0
        if args.action == "off":
            removed = clear_kill_switch(control_dir=args.control_dir)
            print("Kill switch disabled" if removed else "Kill switch already disabled")
            return 0
        active = is_kill_switch_active(control_dir=args.control_dir)
        print(f"Kill switch active: {active}")
        return 0

    if args.cmd == "incident-note":
        path = create_incident_note(
            title=args.title,
            severity=args.severity,
            details=args.details,
            actions=args.actions,
            output_dir=args.output_dir,
        )
        print(f"Incident note created: {path}")
        return 0

    if args.cmd == "notify-template":
        print(build_notify_template(kind=args.kind, context=args.context))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
