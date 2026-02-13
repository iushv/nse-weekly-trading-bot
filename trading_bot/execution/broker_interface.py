from __future__ import annotations

import hashlib
import random
import time
from datetime import datetime
from typing import Any

import requests
from loguru import logger

from trading_bot.config.settings import Config


GROWW_DEFAULT_BASE_URL = "https://api.groww.in"
GROWW_API_VERSION = "1.0"


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class MockGrowwClient:
    """Mock client used for local and paper environments."""

    def __init__(self, api_key: str | None, api_secret: str | None) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.authenticated = False

    def authenticate(self) -> bool:
        logger.info("Authenticating mock broker client")
        self.authenticated = True
        return True

    def place_order(
        self,
        symbol: str,
        quantity: int,
        order_type: str,
        product: str = "DELIVERY",
        price: float | None = None,
    ) -> dict[str, Any]:
        if not self.authenticated:
            raise RuntimeError("Broker client not authenticated")
        return {
            "order_id": f"ORD_{int(time.time() * 1000)}",
            "symbol": symbol,
            "quantity": quantity,
            "order_type": order_type,
            "product": product,
            "price": price,
            "status": "PENDING",
            "timestamp": datetime.now().isoformat(),
        }

    def get_order_status(self, order_id: str) -> str:
        _ = order_id
        return random.choice(["COMPLETE", "PENDING"])  # nosec: B311

    def get_positions(self) -> list[dict[str, Any]]:
        return []

    def get_funds(self) -> dict[str, Any]:
        return {"cash": 100000.0, "collateral": 0.0}

    def get_historical_candles(
        self,
        *,
        exchange: str,
        segment: str,
        groww_symbol: str,
        start_time: str,
        end_time: str,
        candle_interval: str = "1day",
    ) -> list[list[Any]]:
        _ = exchange, segment, groww_symbol, start_time, end_time, candle_interval
        return []

    def get_open_orders(self, segment: str = "CASH") -> list[dict[str, Any]]:
        _ = segment
        return []

    def cancel_order(self, order_id: str, segment: str = "CASH") -> dict[str, Any]:
        _ = segment
        return {"order_id": order_id, "status": "CANCELLED"}


class HttpBrokerClient:
    """
    Generic HTTP client shape for live broker integration.
    Expected endpoints:
    - POST /orders
    - GET /orders/{id}
    - GET /positions
    - GET /funds
    """

    def __init__(self, api_key: str | None, api_secret: str | None, base_url: str) -> None:
        self.api_key = api_key or ""
        self.api_secret = api_secret or ""
        self.base_url = base_url.rstrip("/")
        self.authenticated = False
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "User-Agent": "trading-bot/1.0",
            }
        )

    def authenticate(self) -> bool:
        if not self.api_key or not self.api_secret or not self.base_url:
            raise RuntimeError("HTTP broker client missing credentials/base URL")

        # Default header-based auth pattern; adjust if broker requires OAuth flow.
        self.session.headers.update(
            {
                "X-API-KEY": self.api_key,
                "X-API-SECRET": self.api_secret,
            }
        )
        self.authenticated = True
        return True

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: int = 15,
        retries: int = 3,
    ) -> requests.Response:
        if not self.authenticated:
            raise RuntimeError("HTTP broker client not authenticated")

        url = f"{self.base_url}{path}"
        last_exc: Exception | None = None

        for attempt in range(1, retries + 1):
            try:
                response = self.session.request(method, url, json=json_payload, params=params, timeout=timeout)
                response.raise_for_status()
                return response
            except Exception as exc:
                last_exc = exc
                if attempt < retries:
                    sleep_for = 1.0 * attempt
                    logger.warning(f"Broker HTTP request failed ({attempt}/{retries}) {method} {path}: {exc}. Retrying in {sleep_for:.1f}s")
                    time.sleep(sleep_for)
                else:
                    logger.error(f"Broker HTTP request failed after {retries} attempts: {method} {path} -> {exc}")
        raise RuntimeError(f"Broker HTTP request failed: {method} {path}") from last_exc

    def place_order(
        self,
        symbol: str,
        quantity: int,
        order_type: str,
        product: str = "DELIVERY",
        price: float | None = None,
    ) -> dict[str, Any]:
        payload = {
            "symbol": symbol,
            "quantity": quantity,
            "order_type": order_type,
            "product": product,
            "price": price,
        }
        response = self._request("POST", "/orders", json_payload=payload)
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Invalid broker order response")
        return data

    def get_order_status(self, order_id: str) -> str:
        response = self._request("GET", f"/orders/{order_id}")
        data = response.json()
        if isinstance(data, dict):
            return str(data.get("status", "UNKNOWN"))
        return "UNKNOWN"

    def get_positions(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/positions")
        data = response.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            positions = data.get("positions", [])
            if isinstance(positions, list):
                return positions
        return []

    def get_funds(self) -> dict[str, Any]:
        response = self._request("GET", "/funds")
        data = response.json()
        return data if isinstance(data, dict) else {"cash": 0.0, "collateral": 0.0}

    def get_historical_candles(
        self,
        *,
        exchange: str,
        segment: str,
        groww_symbol: str,
        start_time: str,
        end_time: str,
        candle_interval: str = "1day",
    ) -> list[list[Any]]:
        response = self._request(
            "GET",
            "/historical/candles",
            params={
                "exchange": exchange,
                "segment": segment,
                "groww_symbol": groww_symbol,
                "start_time": start_time,
                "end_time": end_time,
                "candle_interval": candle_interval,
            },
        )
        data = response.json()
        if isinstance(data, dict):
            candles = data.get("candles", [])
            return candles if isinstance(candles, list) else []
        if isinstance(data, list):
            return data
        return []

    def get_open_orders(self, segment: str = "CASH") -> list[dict[str, Any]]:
        _ = segment
        response = self._request("GET", "/orders", params={"status": "OPEN"})
        data = response.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            orders = data.get("orders", [])
            if isinstance(orders, list):
                return orders
        return []

    def cancel_order(self, order_id: str, segment: str = "CASH") -> dict[str, Any]:
        _ = segment
        for method, path, payload in [
            ("POST", f"/orders/{order_id}/cancel", None),
            ("POST", "/orders/cancel", {"order_id": order_id}),
            ("DELETE", f"/orders/{order_id}", None),
        ]:
            try:
                response = self._request(method, path, json_payload=payload)
                data = response.json()
                if isinstance(data, dict):
                    return data
            except Exception:
                continue
        raise RuntimeError(f"Failed to cancel order {order_id}")


class GrowwHttpClient:
    """Groww HTTP implementation using the documented token and trading endpoints."""

    def __init__(
        self,
        api_key: str | None,
        api_secret: str | None,
        *,
        token_mode: str = "approval",
        base_url: str | None = None,
        access_token: str | None = None,
        totp: str | None = None,
        app_id: str | None = None,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.api_secret = (api_secret or "").strip()
        self.token_mode = (token_mode or "approval").strip().lower()
        self.base_url = (base_url or GROWW_DEFAULT_BASE_URL).strip().rstrip("/")
        self.access_token = (access_token or "").strip()
        self.totp = (totp or "").strip()
        self.app_id = (app_id or "").strip()
        self.authenticated = False
        self._historical_primary_supported: bool | None = None
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "trading-bot/1.0",
                "X-API-VERSION": GROWW_API_VERSION,
            }
        )

    def _normalize_token_mode(self) -> str:
        alias_map = {
            "access": "access_token",
            "bearer": "access_token",
            "direct": "access_token",
        }
        return alias_map.get(self.token_mode, self.token_mode)

    def _set_access_token(self, access_token: str) -> None:
        self.access_token = access_token
        self.session.headers["Authorization"] = f"Bearer {access_token}"

    def _parse_error_message(self, response_data: dict[str, Any]) -> str:
        error = response_data.get("error")
        if isinstance(error, dict):
            for key in ("message", "error_message", "description", "code"):
                value = error.get(key)
                if value:
                    return str(value)
        if isinstance(error, str) and error:
            return error
        message = response_data.get("message")
        if message:
            return str(message)
        return "Unknown broker error"

    def _request_access_token(self) -> str:
        mode = self._normalize_token_mode()
        payload: dict[str, Any]

        if mode == "approval":
            # Groww requires epoch seconds (10 digits) for checksum and request body.
            timestamp = str(int(time.time()))
            checksum_data = f"{self.api_secret}{timestamp}".encode("utf-8")
            checksum = hashlib.sha256(checksum_data).hexdigest()
            payload = {
                "key_type": "approval",
                "checksum": checksum,
                "timestamp": timestamp,
            }
            if self.app_id:
                payload["app_id"] = self.app_id
        elif mode == "totp":
            if not self.totp:
                raise RuntimeError("Groww TOTP token is required when GROWW_TOKEN_MODE=totp")
            payload = {"key_type": "totp", "totp": self.totp}
            if self.app_id:
                payload["app_id"] = self.app_id
        else:
            raise RuntimeError(f"Unsupported Groww token mode: {self.token_mode}")

        response = self.session.post(
            f"{self.base_url}/v1/token/api/access",
            json=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-API-VERSION": GROWW_API_VERSION,
            },
            timeout=20,
        )
        data: dict[str, Any] = {}
        try:
            maybe_data = response.json()
            if isinstance(maybe_data, dict):
                data = maybe_data
        except Exception:
            data = {}

        if response.status_code >= 400:
            message = self._parse_error_message(data) if data else response.text
            raise RuntimeError(f"Groww token API error ({response.status_code}): {message}")

        if not isinstance(data, dict):
            raise RuntimeError("Invalid Groww token response format")

        status = str(data.get("status", "")).upper()
        if status and status != "SUCCESS":
            raise RuntimeError(self._parse_error_message(data))

        payload_data = data.get("payload", {}) if isinstance(data.get("payload"), dict) else {}
        token = str(
            data.get("token")
            or data.get("access_token")
            or payload_data.get("access_token")
            or payload_data.get("token")
            or payload_data.get("api_token")
            or ""
        )
        if not token:
            raise RuntimeError("Missing access token in Groww token response")
        return token

    def _refresh_access_token(self) -> None:
        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                token = self._request_access_token()
                self._set_access_token(token)
                self.authenticated = True
                logger.info("Groww access token refreshed successfully")
                return
            except Exception as exc:
                last_exc = exc
                if attempt < 3:
                    sleep_for = float(attempt)
                    logger.warning(f"Groww token refresh failed ({attempt}/3): {exc}. Retrying in {sleep_for:.1f}s")
                    time.sleep(sleep_for)
                else:
                    logger.error(f"Groww token refresh failed after 3 attempts: {exc}")
        raise RuntimeError("Failed to obtain Groww access token") from last_exc

    def authenticate(self) -> bool:
        if not self.api_key:
            raise RuntimeError("Groww API key is required")

        mode = self._normalize_token_mode()
        if mode == "access_token":
            token = self.access_token or self.api_key
            self._set_access_token(token)
            self.authenticated = True
            return True

        if mode == "approval" and not self.api_secret:
            raise RuntimeError("Groww API secret is required when GROWW_TOKEN_MODE=approval")

        if mode in {"approval", "totp"}:
            self._refresh_access_token()
            return True

        raise RuntimeError(f"Unsupported GROWW_TOKEN_MODE: {self.token_mode}")

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: int = 20,
        retries: int = 3,
    ) -> dict[str, Any]:
        if not self.authenticated:
            raise RuntimeError("Groww client is not authenticated")

        url = f"{self.base_url}{path}"
        last_exc: Exception | None = None

        for attempt in range(1, retries + 1):
            try:
                response = self.session.request(
                    method,
                    url,
                    json=json_payload,
                    params=params,
                    timeout=timeout,
                )

                if (
                    response.status_code == 401
                    and self._normalize_token_mode() in {"approval", "totp"}
                ):
                    logger.warning("Groww request unauthorized; refreshing token and retrying once")
                    self._refresh_access_token()
                    response = self.session.request(
                        method,
                        url,
                        json=json_payload,
                        params=params,
                        timeout=timeout,
                    )

                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise RuntimeError(f"Invalid response format from {path}")
                return data
            except Exception as exc:
                last_exc = exc
                if attempt < retries:
                    sleep_for = float(attempt)
                    logger.warning(
                        f"Groww request failed ({attempt}/{retries}) {method} {path}: {exc}. "
                        f"Retrying in {sleep_for:.1f}s"
                    )
                    time.sleep(sleep_for)
                else:
                    logger.error(f"Groww request failed after {retries} attempts: {method} {path} -> {exc}")
        raise RuntimeError(f"Groww request failed: {method} {path}") from last_exc

    def _extract_payload(self, response_data: dict[str, Any]) -> Any:
        status = str(response_data.get("status", "")).upper()
        if status and status != "SUCCESS":
            raise RuntimeError(self._parse_error_message(response_data))
        if "payload" in response_data:
            return response_data["payload"]
        return response_data

    def _build_order_payload(
        self,
        symbol: str,
        quantity: int,
        order_type: str,
        product: str,
        price: float | None,
    ) -> dict[str, Any]:
        normalized_order = order_type.upper()
        transaction_type = "BUY"
        groww_order_type = "MARKET"
        limit_price: float | None = None
        trigger_price: float | None = None

        if normalized_order in {"BUY", "SELL"}:
            transaction_type = normalized_order
        elif normalized_order in {"BUY_LIMIT", "SELL_LIMIT"}:
            transaction_type = normalized_order.replace("_LIMIT", "")
            groww_order_type = "LIMIT"
            if price is None:
                raise RuntimeError("Limit order requires a valid price")
            limit_price = float(price)
        elif normalized_order in {"SELL_STOP_LOSS", "BUY_STOP_LOSS"}:
            transaction_type = normalized_order.replace("_STOP_LOSS", "")
            # Groww annexures define stop-loss market order type as SL_M.
            groww_order_type = "SL_M"
            if price is None:
                raise RuntimeError("Stop-loss order requires a valid trigger price")
            trigger_price = float(price)
        else:
            raise RuntimeError(f"Unsupported order type: {order_type}")

        product_map = {
            "DELIVERY": "CNC",
            "CNC": "CNC",
            "INTRADAY": "MIS",
            "MIS": "MIS",
            "NRML": "NRML",
        }
        groww_product = product_map.get(product.upper(), "CNC")

        payload: dict[str, Any] = {
            "trading_symbol": symbol,
            "transaction_type": transaction_type,
            "exchange": "NSE",
            "segment": "CASH",
            "order_type": groww_order_type,
            "product": groww_product,
            "validity": "DAY",
            "quantity": int(quantity),
            "order_reference_id": f"TB-{int(time.time() * 1000)}",
        }
        if limit_price is not None:
            payload["price"] = limit_price
        if trigger_price is not None:
            payload["trigger_price"] = trigger_price
        return payload

    def place_order(
        self,
        symbol: str,
        quantity: int,
        order_type: str,
        product: str = "DELIVERY",
        price: float | None = None,
    ) -> dict[str, Any]:
        payload = self._build_order_payload(symbol, quantity, order_type, product, price)
        data = self._request_json("POST", "/v1/order/create", json_payload=payload)
        payload_data = self._extract_payload(data)
        if not isinstance(payload_data, dict):
            raise RuntimeError("Invalid Groww order response payload")

        groww_order_id = payload_data.get("groww_order_id")
        order_reference_id = payload_data.get("order_reference_id") or payload["order_reference_id"]
        order_id = str(
            groww_order_id
            or payload_data.get("order_id")
            or payload_data.get("id")
            or payload_data.get("orderId")
            or order_reference_id
        )
        status = str(payload_data.get("order_status") or payload_data.get("status") or "PENDING").upper()
        return {
            "order_id": order_id,
            "groww_order_id": str(groww_order_id) if groww_order_id else None,
            "order_reference_id": str(order_reference_id),
            "symbol": symbol,
            "quantity": int(quantity),
            "order_type": order_type,
            "product": product,
            "price": price,
            "status": status,
            "raw": payload_data,
        }

    def get_order_status(self, order_id: str) -> str:
        data = self._request_json(
            "GET",
            f"/v1/order/status/{order_id}",
            params={"segment": "CASH"},
        )
        payload_data = self._extract_payload(data)
        if not isinstance(payload_data, dict):
            return "UNKNOWN"

        raw_status = str(payload_data.get("order_status") or payload_data.get("status") or "UNKNOWN").upper()
        status_map = {
            "EXECUTED": "COMPLETE",
            "COMPLETE": "COMPLETE",
            "NEW": "PENDING",
            "OPEN": "PENDING",
            "PARTIAL_EXECUTED": "PENDING",
            "CANCELLED": "CANCELLED",
            "REJECTED": "REJECTED",
            "FAILED": "FAILED",
            "EXPIRED": "CANCELLED",
        }
        return status_map.get(raw_status, raw_status)

    def get_positions(self) -> list[dict[str, Any]]:
        data = self._request_json("GET", "/v1/positions/user", params={"segment": "CASH"})
        payload_data = self._extract_payload(data)
        if isinstance(payload_data, dict):
            positions = payload_data.get("positions", [])
        elif isinstance(payload_data, list):
            positions = payload_data
        else:
            positions = []

        if not isinstance(positions, list):
            return []

        normalized_positions: list[dict[str, Any]] = []
        for item in positions:
            if not isinstance(item, dict):
                continue
            normalized_positions.append(
                {
                    "symbol": item.get("trading_symbol") or item.get("symbol") or "",
                    "quantity": _to_int(item.get("quantity") or item.get("net_quantity")),
                    "average_price": _to_float(item.get("average_price") or item.get("avg_price")),
                    "pnl": _to_float(item.get("pnl") or item.get("unrealized_pnl")),
                    "raw": item,
                }
            )
        return normalized_positions

    def get_funds(self) -> dict[str, Any]:
        data = self._request_json("GET", "/v1/margins/detail/user")
        payload_data = self._extract_payload(data)
        if not isinstance(payload_data, dict):
            return {"cash": 0.0, "collateral": 0.0}
        return {
            "cash": _to_float(payload_data.get("clear_cash") or payload_data.get("cash")),
            "collateral": _to_float(payload_data.get("collateral_amount") or payload_data.get("collateral")),
            "raw": payload_data,
        }

    def get_historical_candles(
        self,
        *,
        exchange: str,
        segment: str,
        groww_symbol: str,
        start_time: str,
        end_time: str,
        candle_interval: str = "1day",
    ) -> list[list[Any]]:
        if self._historical_primary_supported is not False:
            params = {
                "exchange": exchange,
                "segment": segment,
                "groww_symbol": groww_symbol,
                "start_time": start_time,
                "end_time": end_time,
                "candle_interval": candle_interval,
            }
            try:
                data = self._request_json(
                    "GET",
                    "/v1/historical/candles",
                    params=params,
                    retries=1,
                )
                payload_data = self._extract_payload(data)
                candles = self._extract_candle_rows(payload_data)
                self._historical_primary_supported = True
                if candles:
                    return candles
                logger.warning(
                    "Groww primary historical endpoint returned no candles for "
                    f"{groww_symbol} {start_time}->{end_time}; trying legacy endpoint"
                )
            except Exception as exc:
                if self._is_primary_historical_unsupported(exc):
                    if self._historical_primary_supported is not False:
                        logger.warning(
                            "Groww primary historical endpoint unavailable for this account; "
                            "switching to legacy endpoint for subsequent requests"
                        )
                    self._historical_primary_supported = False
                logger.warning(
                    "Groww primary historical endpoint failed for "
                    f"{groww_symbol} {start_time}->{end_time}: {exc}. Trying legacy endpoint"
                )

        trading_symbol = self._extract_trading_symbol(groww_symbol, exchange=exchange)
        legacy_params = {
            "exchange": exchange,
            "segment": segment,
            "trading_symbol": trading_symbol,
            "start_time": start_time,
            "end_time": end_time,
            "interval_in_minutes": self._interval_to_minutes(candle_interval),
        }
        legacy_data = self._request_json(
            "GET",
            "/v1/historical/candle/range",
            params=legacy_params,
            retries=1,
        )
        legacy_payload = self._extract_payload(legacy_data)
        return self._extract_candle_rows(legacy_payload)

    @staticmethod
    def _is_primary_historical_unsupported(exc: Exception) -> bool:
        messages = [str(exc).lower()]
        cause = exc.__cause__
        while cause is not None:
            messages.append(str(cause).lower())
            cause = cause.__cause__
        message = " | ".join(messages)
        return (
            "403" in message
            or "forbidden" in message
            or "404" in message
            or "not found" in message
        )

    @staticmethod
    def _extract_trading_symbol(groww_symbol: str, *, exchange: str) -> str:
        prefix = f"{exchange.upper()}-"
        normalized = groww_symbol.strip()
        if normalized.upper().startswith(prefix):
            return normalized[len(prefix) :]
        if "-" in normalized:
            return normalized.split("-", 1)[1]
        return normalized

    @staticmethod
    def _interval_to_minutes(candle_interval: str) -> int:
        interval = candle_interval.strip().lower()
        mapping = {
            "1m": 1,
            "3m": 3,
            "5m": 5,
            "10m": 10,
            "15m": 15,
            "30m": 30,
            "60m": 60,
            "1h": 60,
            "2h": 120,
            "4h": 240,
            "1day": 1440,
            "day": 1440,
            "1d": 1440,
            "1week": 10080,
            "week": 10080,
            "1w": 10080,
        }
        if interval in mapping:
            return mapping[interval]
        return 1440

    @staticmethod
    def _extract_candle_rows(payload_data: Any) -> list[list[Any]]:
        if isinstance(payload_data, list):
            return GrowwHttpClient._normalize_candle_rows(payload_data)
        if isinstance(payload_data, dict):
            for key in ("candles", "data", "historical_candles"):
                rows = payload_data.get(key)
                if isinstance(rows, list):
                    return GrowwHttpClient._normalize_candle_rows(rows)
        return []

    @staticmethod
    def _normalize_candle_rows(rows: list[Any]) -> list[list[Any]]:
        normalized: list[list[Any]] = []
        for row in rows:
            if isinstance(row, (list, tuple)) and len(row) >= 6:
                normalized.append(list(row[:6]))
                continue
            if not isinstance(row, dict):
                continue

            timestamp = (
                row.get("timestamp")
                or row.get("time")
                or row.get("date")
                or row.get("epoch")
            )
            open_price = row.get("open") if row.get("open") is not None else row.get("Open")
            high_price = row.get("high") if row.get("high") is not None else row.get("High")
            low_price = row.get("low") if row.get("low") is not None else row.get("Low")
            close_price = row.get("close") if row.get("close") is not None else row.get("Close")
            volume = row.get("volume") if row.get("volume") is not None else row.get("Volume")

            if any(value is None for value in (timestamp, open_price, high_price, low_price, close_price, volume)):
                continue
            normalized.append([timestamp, open_price, high_price, low_price, close_price, volume])
        return normalized

    def get_open_orders(self, segment: str = "CASH") -> list[dict[str, Any]]:
        open_like = {
            "OPEN",
            "NEW",
            "PENDING",
            "PARTIAL_EXECUTED",
            "TRIGGER_PENDING",
            "VALIDATION_PENDING",
        }
        normalized: list[dict[str, Any]] = []
        for page in range(0, 3):
            data = self._request_json(
                "GET",
                "/v1/order/list",
                params={"segment": segment, "page": page, "page_size": 100},
            )
            payload_data = self._extract_payload(data)
            if isinstance(payload_data, dict):
                # Current Groww schema returns payload.order_list.
                # Keep fallback to payload.orders for backward compatibility.
                orders = payload_data.get("order_list", payload_data.get("orders", []))
            elif isinstance(payload_data, list):
                orders = payload_data
            else:
                orders = []

            if not isinstance(orders, list) or not orders:
                break

            for item in orders:
                if not isinstance(item, dict):
                    continue
                status = str(item.get("order_status") or item.get("status") or "").upper()
                if status not in open_like:
                    continue
                groww_order_id = item.get("groww_order_id")
                order_ref = item.get("order_reference_id")
                order_id = str(
                    groww_order_id
                    or item.get("order_id")
                    or item.get("id")
                    or order_ref
                    or ""
                )
                if not order_id:
                    continue
                normalized.append(
                    {
                        "order_id": order_id,
                        "groww_order_id": str(groww_order_id) if groww_order_id else None,
                        "order_reference_id": str(order_ref) if order_ref else None,
                        "status": status,
                        "symbol": item.get("trading_symbol") or item.get("symbol"),
                        "quantity": _to_int(item.get("quantity")),
                        "raw": item,
                    }
                )
            if len(orders) < 100:
                break

        return normalized

    def cancel_order(self, order_id: str, segment: str = "CASH") -> dict[str, Any]:
        payload_variants = [
            {"segment": segment, "groww_order_id": order_id},
            {"segment": segment, "order_id": order_id},
        ]
        last_error: Exception | None = None
        for payload in payload_variants:
            try:
                data = self._request_json("POST", "/v1/order/cancel", json_payload=payload)
                payload_data = self._extract_payload(data)
                if isinstance(payload_data, dict):
                    raw_status = str(payload_data.get("order_status") or payload_data.get("status") or "CANCELLED").upper()
                    return {
                        "order_id": str(
                            payload_data.get("groww_order_id")
                            or payload_data.get("order_id")
                            or payload_data.get("id")
                            or order_id
                        ),
                        "status": raw_status,
                        "raw": payload_data,
                    }
                return {"order_id": order_id, "status": "CANCELLED", "raw": payload_data}
            except Exception as exc:
                last_error = exc
                continue
        raise RuntimeError(f"Failed to cancel Groww order {order_id}") from last_error


class BrokerInterface:
    def __init__(self) -> None:
        self.provider = Config.BROKER_PROVIDER
        if self.provider in {"groww", "groww_http"}:
            self.client: MockGrowwClient | HttpBrokerClient | GrowwHttpClient = GrowwHttpClient(
                api_key=Config.GROWW_API_KEY,
                api_secret=Config.GROWW_API_SECRET,
                token_mode=Config.GROWW_TOKEN_MODE,
                base_url=Config.BROKER_BASE_URL or GROWW_DEFAULT_BASE_URL,
                access_token=Config.GROWW_ACCESS_TOKEN,
                totp=Config.GROWW_TOTP,
                app_id=Config.GROWW_APP_ID,
            )
        elif self.provider == "http":
            self.client = HttpBrokerClient(
                api_key=Config.GROWW_API_KEY,
                api_secret=Config.GROWW_API_SECRET,
                base_url=Config.BROKER_BASE_URL,
            )
        else:
            self.client = MockGrowwClient(Config.GROWW_API_KEY, Config.GROWW_API_SECRET)

        self.retry_attempts = 3
        self.retry_delay = 2

    def connect(self) -> bool:
        try:
            ok = self.client.authenticate()
            logger.info(f"Broker connected using provider={self.provider}")
            return ok
        except Exception as exc:
            logger.error(f"Broker connect failed: {exc}")
            return False

    def place_market_order(self, symbol: str, quantity: int, action: str) -> dict[str, Any] | None:
        clean = symbol.replace(".NS", "")
        for attempt in range(self.retry_attempts):
            try:
                return self.client.place_order(clean, quantity, action, product="DELIVERY")
            except Exception as exc:
                logger.error(f"Market order failed attempt {attempt + 1}: {exc}")
                if attempt < self.retry_attempts - 1:
                    time.sleep(self.retry_delay)
        return None

    def place_limit_order(self, symbol: str, quantity: int, action: str, price: float) -> dict[str, Any] | None:
        clean = symbol.replace(".NS", "")
        try:
            return self.client.place_order(clean, quantity, f"{action}_LIMIT", product="DELIVERY", price=price)
        except Exception as exc:
            logger.error(f"Limit order failed: {exc}")
            return None

    def place_stop_loss_order(self, symbol: str, quantity: int, stop_price: float) -> dict[str, Any] | None:
        clean = symbol.replace(".NS", "")
        try:
            return self.client.place_order(clean, quantity, "SELL_STOP_LOSS", product="DELIVERY", price=stop_price)
        except Exception as exc:
            logger.error(f"Stop-loss order failed: {exc}")
            return None

    def get_order_status(self, order_id: str) -> str:
        try:
            return self.client.get_order_status(order_id)
        except Exception as exc:
            logger.error(f"Order status fetch failed: {exc}")
            return "UNKNOWN"

    def wait_for_order_completion(self, order_id: str, timeout: int = 30) -> bool:
        start = time.time()
        while time.time() - start < timeout:
            status = self.get_order_status(order_id)
            if status == "COMPLETE":
                return True
            if status in {"REJECTED", "CANCELLED", "FAILED"}:
                return False
            time.sleep(2)
        return False

    def get_available_cash(self) -> float:
        try:
            return float(self.client.get_funds().get("cash", 0.0))
        except Exception as exc:
            logger.error(f"Funds fetch failed: {exc}")
            return 0.0

    def get_current_positions(self) -> list[dict[str, Any]]:
        try:
            return self.client.get_positions()
        except Exception as exc:
            logger.error(f"Positions fetch failed: {exc}")
            return []

    def get_historical_candles(
        self,
        *,
        exchange: str,
        segment: str,
        groww_symbol: str,
        start_time: str,
        end_time: str,
        candle_interval: str = "1day",
    ) -> list[list[Any]]:
        try:
            getter = getattr(self.client, "get_historical_candles", None)
            if not callable(getter):
                return []
            candles = getter(
                exchange=exchange,
                segment=segment,
                groww_symbol=groww_symbol,
                start_time=start_time,
                end_time=end_time,
                candle_interval=candle_interval,
            )
            return candles if isinstance(candles, list) else []
        except Exception as exc:
            logger.error(f"Historical candles fetch failed for {groww_symbol}: {exc}")
            return []

    def get_open_orders(self, segment: str = "CASH") -> list[dict[str, Any]]:
        try:
            getter = getattr(self.client, "get_open_orders", None)
            if callable(getter):
                orders = getter(segment)
                return orders if isinstance(orders, list) else []
            return []
        except Exception as exc:
            logger.error(f"Open orders fetch failed: {exc}")
            return []

    def cancel_order(self, order_id: str, segment: str = "CASH") -> dict[str, Any] | None:
        try:
            canceller = getattr(self.client, "cancel_order", None)
            if not callable(canceller):
                logger.error("Broker client does not support order cancellation")
                return None
            result = canceller(order_id, segment)
            if isinstance(result, dict):
                return result
            return {"order_id": order_id, "status": "UNKNOWN"}
        except Exception as exc:
            logger.error(f"Order cancel failed for {order_id}: {exc}")
            return None


broker = BrokerInterface()
