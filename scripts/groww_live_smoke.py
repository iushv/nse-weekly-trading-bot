from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import text


def _require(name: str, value: str | None) -> str:
    if value and value.strip():
        return value.strip()
    raise ValueError(f"Missing required environment variable: {name}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safe Groww live smoke test (read-only by default).",
    )
    parser.add_argument("--token-mode", default=os.getenv("GROWW_TOKEN_MODE", "approval"))
    parser.add_argument("--base-url", default=(os.getenv("BROKER_BASE_URL") or "https://api.groww.in"))

    parser.add_argument("--check-auth", action="store_true", default=True)
    parser.add_argument("--check-funds", action="store_true", default=True)
    parser.add_argument("--check-positions", action="store_true", default=True)

    parser.add_argument("--place-order", action="store_true", help="Optional: place one live order.")
    parser.add_argument("--symbol", default="RELIANCE")
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--action", choices=["BUY", "SELL"], default="BUY")
    parser.add_argument(
        "--simulate-funds",
        type=float,
        default=None,
        help="Optional: simulate available cash and avoid live order placement.",
    )
    parser.add_argument(
        "--simulate-order-price",
        type=float,
        default=3000.0,
        help="Estimated price per share used for simulated order checks.",
    )
    parser.add_argument(
        "--simulate-roundtrip",
        action="store_true",
        help="Simulate BUY->SELL roundtrip and compute P&L (requires --simulate-funds).",
    )
    parser.add_argument(
        "--simulate-exit-price",
        type=float,
        default=None,
        help="Optional simulated exit price for roundtrip. Defaults to +2%% from entry.",
    )
    parser.add_argument(
        "--persist-db",
        action="store_true",
        help="Persist simulated closed roundtrip trade to local trades table.",
    )
    parser.add_argument(
        "--strategy-name",
        default="groww_smoke_roundtrip",
        help="Strategy label used when persisting simulated trade.",
    )
    parser.add_argument(
        "--exit-reason",
        default="SMOKE_SIMULATION",
        help="Exit reason label used when persisting simulated trade.",
    )
    parser.add_argument(
        "--force",
        default="",
        help="Required with --place-order. Must be exactly YES_PLACE_LIVE_ORDER.",
    )
    return parser


def _print_heading(title: str) -> None:
    print(f"\n=== {title} ===")


def _safe_preview_positions(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preview: list[dict[str, Any]] = []
    for item in positions[:5]:
        preview.append(
            {
                "symbol": item.get("symbol"),
                "quantity": item.get("quantity"),
                "average_price": item.get("average_price"),
                "pnl": item.get("pnl"),
            }
        )
    return preview


def _simulate_order(symbol: str, quantity: int, action: str, funds: float, price: float) -> dict[str, Any]:
    from trading_bot.config.settings import Config

    transaction_cost = float(Config.COST_PER_SIDE)
    required_cash = quantity * price * (1.0 + transaction_cost)
    status = "COMPLETE" if funds >= required_cash else "FAILED"
    remark = (
        "Simulated acceptance"
        if status == "COMPLETE"
        else f"Simulated insufficient funds: need {required_cash:.2f}, have {funds:.2f}"
    )
    return {
        "order_id": f"SIM-{int(quantity * price)}",
        "symbol": symbol,
        "quantity": quantity,
        "order_type": action,
        "status": status,
        "remark": remark,
        "required_cash": required_cash,
    }


def _calculate_roundtrip(
    action: str,
    quantity: int,
    entry_price: float,
    exit_price: float,
    side_cost_rate: float,
) -> dict[str, float]:
    direction = 1.0 if action.upper() == "BUY" else -1.0
    entry_value = quantity * entry_price
    exit_value = quantity * exit_price
    gross_pnl = (exit_price - entry_price) * quantity * direction
    total_cost = (entry_value + exit_value) * side_cost_rate
    net_pnl = gross_pnl - total_cost
    invested = entry_value * (1.0 + side_cost_rate)
    pnl_percent = (net_pnl / invested) * 100.0 if invested > 0 else 0.0
    return {
        "entry_value": entry_value,
        "exit_value": exit_value,
        "gross_pnl": gross_pnl,
        "total_cost": total_cost,
        "net_pnl": net_pnl,
        "pnl_percent": pnl_percent,
    }


def _persist_closed_trade(
    *,
    order_id: str,
    symbol: str,
    action: str,
    quantity: int,
    entry_price: float,
    exit_price: float,
    pnl: float,
    pnl_percent: float,
    strategy: str,
    exit_reason: str,
) -> dict[str, Any]:
    from trading_bot.data.storage.database import db

    db.init_db()
    now = datetime.now()
    entry_date = (now - timedelta(minutes=5)).isoformat()
    exit_date = now.isoformat()

    insert_query = text(
        """
        INSERT OR REPLACE INTO trades (
            order_id, symbol, strategy, action, quantity, entry_price, entry_date,
            exit_price, exit_date, stop_loss, target, pnl, pnl_percent, status, notes
        ) VALUES (
            :order_id, :symbol, :strategy, :action, :quantity, :entry_price, :entry_date,
            :exit_price, :exit_date, :stop_loss, :target, :pnl, :pnl_percent, :status, :notes
        )
        """
    )
    payload = {
        "order_id": order_id,
        "symbol": symbol,
        "strategy": strategy,
        "action": action,
        "quantity": quantity,
        "entry_price": entry_price,
        "entry_date": entry_date,
        "exit_price": exit_price,
        "exit_date": exit_date,
        "stop_loss": None,
        "target": None,
        "pnl": pnl,
        "pnl_percent": pnl_percent,
        "status": "CLOSED",
        "notes": exit_reason,
    }

    with db.engine.begin() as conn:
        conn.execute(insert_query, payload)
        row = conn.execute(
            text(
                """
                SELECT order_id, symbol, strategy, action, quantity, pnl, pnl_percent, status, notes
                FROM trades
                WHERE order_id = :order_id
                LIMIT 1
                """
            ),
            {"order_id": order_id},
        ).mappings().first()

    return dict(row) if row else {}


def main() -> int:
    load_dotenv()
    parser = _build_parser()
    args = parser.parse_args()

    from trading_bot.execution.broker_interface import GrowwHttpClient

    try:
        api_key = _require("GROWW_API_KEY", os.getenv("GROWW_API_KEY"))
        token_mode = (args.token_mode or "approval").strip().lower()
        api_secret = os.getenv("GROWW_API_SECRET", "")
        access_token = os.getenv("GROWW_ACCESS_TOKEN", "")
        totp = os.getenv("GROWW_TOTP", "")
        app_id = os.getenv("GROWW_APP_ID", "")

        if token_mode == "approval":
            _require("GROWW_API_SECRET", api_secret)
        elif token_mode == "totp":
            _require("GROWW_TOTP", totp)
        elif token_mode in {"access_token", "access", "bearer", "direct"}:
            if not access_token and not api_key:
                raise ValueError("Missing GROWW_ACCESS_TOKEN or GROWW_API_KEY for access token mode.")
        else:
            raise ValueError(f"Unsupported token mode: {token_mode}")

        client = GrowwHttpClient(
            api_key=api_key,
            api_secret=api_secret,
            token_mode=token_mode,
            base_url=args.base_url,
            access_token=access_token,
            totp=totp,
            app_id=app_id,
        )

        _print_heading("Authentication")
        if args.check_auth:
            ok = client.authenticate()
            print(f"connected={ok} mode={token_mode} base_url={args.base_url}")

        if args.check_funds:
            _print_heading("Funds")
            funds = (
                {"cash": float(args.simulate_funds), "collateral": 0.0}
                if args.simulate_funds is not None
                else client.get_funds()
            )
            print(
                "cash={cash:.2f} collateral={collateral:.2f}".format(
                    cash=float(funds.get("cash", 0.0)),
                    collateral=float(funds.get("collateral", 0.0)),
                )
            )

        if args.check_positions:
            _print_heading("Positions")
            positions = client.get_positions()
            print(f"count={len(positions)} preview={_safe_preview_positions(positions)}")

        if args.simulate_roundtrip and not args.place_order:
            raise ValueError("--simulate-roundtrip requires --place-order.")
        if args.simulate_roundtrip and args.simulate_funds is None:
            raise ValueError("--simulate-roundtrip requires --simulate-funds to avoid live order side-effects.")

        order: dict[str, Any] | None = None
        if args.place_order:
            from trading_bot.config.settings import Config

            armed_by_config = bool(Config.LIVE_ORDER_EXECUTION_ENABLED)
            ack_ok = Config.LIVE_ORDER_FORCE_ACK == Config.LIVE_ORDER_ACK_PHRASE
            if not (armed_by_config and ack_ok):
                raise ValueError(
                    "Live order placement blocked by safety lock. "
                    "Set LIVE_ORDER_EXECUTION_ENABLED=1 and LIVE_ORDER_FORCE_ACK="
                    f"{Config.LIVE_ORDER_ACK_PHRASE} before using --place-order."
                )
            if args.force != "YES_PLACE_LIVE_ORDER":
                raise ValueError(
                    "Refusing to place live order. Re-run with --force YES_PLACE_LIVE_ORDER "
                    "to confirm."
                )
            _print_heading("Live Order")
            if args.simulate_funds is not None:
                order = _simulate_order(
                    symbol=args.symbol,
                    quantity=args.quantity,
                    action=args.action,
                    funds=float(args.simulate_funds),
                    price=float(args.simulate_order_price),
                )
                print("mode=SIMULATED_FUNDS")
            else:
                order = client.place_order(args.symbol, args.quantity, args.action, product="DELIVERY")
            print(
                "submitted order_id={order_id} symbol={symbol} quantity={quantity} status={status}".format(
                    order_id=order.get("order_id"),
                    symbol=order.get("symbol"),
                    quantity=order.get("quantity"),
                    status=order.get("status"),
                )
            )
            if order.get("remark"):
                print(f"remark={order['remark']}")
            if order.get("required_cash") is not None:
                print(f"required_cash={float(order['required_cash']):.2f}")

        if args.simulate_roundtrip:
            if not order or str(order.get("status", "")).upper() != "COMPLETE":
                raise ValueError("Roundtrip simulation requires successful simulated entry order.")

            _print_heading("Simulated Roundtrip")
            entry_price = float(args.simulate_order_price)
            exit_price = (
                float(args.simulate_exit_price)
                if args.simulate_exit_price is not None
                else round(entry_price * 1.02, 2)
            )
            quantity = int(args.quantity)
            action = str(args.action).upper()

            from trading_bot.config.settings import Config

            metrics = _calculate_roundtrip(
                action=action,
                quantity=quantity,
                entry_price=entry_price,
                exit_price=exit_price,
                side_cost_rate=Config.COST_PER_SIDE,
            )
            print(f"entry_price={entry_price:.2f} exit_price={exit_price:.2f} quantity={quantity}")
            print(
                "gross_pnl={gross:.2f} total_cost={cost:.2f} net_pnl={net:.2f} pnl_percent={pct:.2f}".format(
                    gross=metrics["gross_pnl"],
                    cost=metrics["total_cost"],
                    net=metrics["net_pnl"],
                    pct=metrics["pnl_percent"],
                )
            )

            if args.persist_db:
                persisted_order_id = f"{order.get('order_id', 'SIM')}-RT"
                persisted = _persist_closed_trade(
                    order_id=persisted_order_id,
                    symbol=str(args.symbol),
                    action=action,
                    quantity=quantity,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    pnl=metrics["net_pnl"],
                    pnl_percent=metrics["pnl_percent"],
                    strategy=str(args.strategy_name),
                    exit_reason=str(args.exit_reason),
                )
                _print_heading("DB Persistence")
                if persisted:
                    print(
                        "saved order_id={order_id} symbol={symbol} strategy={strategy} status={status} pnl={pnl:.2f}".format(
                            order_id=persisted.get("order_id"),
                            symbol=persisted.get("symbol"),
                            strategy=persisted.get("strategy"),
                            status=persisted.get("status"),
                            pnl=float(persisted.get("pnl", 0.0)),
                        )
                    )
                else:
                    print("No persisted row returned.")

        _print_heading("Result")
        print("Smoke test completed.")
        return 0
    except Exception as exc:
        print(f"Smoke test failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
