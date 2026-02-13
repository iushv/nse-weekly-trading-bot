from __future__ import annotations

from typing import Any

from trading_bot.config.settings import Config
from trading_bot.execution import broker_interface as broker_mod
from trading_bot.execution.broker_interface import BrokerInterface


def test_broker_connect_sets_authenticated():
    broker = BrokerInterface()
    assert broker.connect() is True
    assert broker.client.authenticated is True


def test_market_order_retries_and_strips_ns_suffix(monkeypatch):
    broker = BrokerInterface()
    broker.connect()

    attempts = {"count": 0}

    def flaky_place_order(symbol, quantity, order_type, product="DELIVERY", price=None):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("temporary failure")
        return {
            "order_id": "ORD_RETRY_OK",
            "symbol": symbol,
            "quantity": quantity,
            "order_type": order_type,
            "status": "PENDING",
            "price": price,
            "product": product,
        }

    monkeypatch.setattr(broker.client, "place_order", flaky_place_order)
    monkeypatch.setattr(broker_mod.time, "sleep", lambda _seconds: None)

    order = broker.place_market_order("RELIANCE.NS", 5, "BUY")
    assert order is not None
    assert order["symbol"] == "RELIANCE"
    assert attempts["count"] == 3


def test_wait_for_order_completion_success_and_timeout(monkeypatch):
    broker = BrokerInterface()

    statuses = iter(["PENDING", "PENDING", "COMPLETE"])
    monkeypatch.setattr(broker, "get_order_status", lambda _order_id: next(statuses))
    monkeypatch.setattr(broker_mod.time, "sleep", lambda _seconds: None)
    assert broker.wait_for_order_completion("ORD_1", timeout=2) is True

    monkeypatch.setattr(broker, "get_order_status", lambda _order_id: "PENDING")
    assert broker.wait_for_order_completion("ORD_2", timeout=0) is False


def test_broker_funds_and_positions_contract(monkeypatch):
    broker = BrokerInterface()
    monkeypatch.setattr(broker.client, "get_funds", lambda: {"cash": 12345.67, "collateral": 0.0})
    monkeypatch.setattr(broker.client, "get_positions", lambda: [{"symbol": "INFY", "quantity": 3}])

    assert broker.get_available_cash() == 12345.67
    positions = broker.get_current_positions()
    assert isinstance(positions, list)
    assert positions[0]["symbol"] == "INFY"


def test_broker_open_orders_and_cancel_contract(monkeypatch):
    broker = BrokerInterface()
    monkeypatch.setattr(broker.client, "get_open_orders", lambda _segment="CASH": [{"order_id": "OID1"}])
    monkeypatch.setattr(broker.client, "cancel_order", lambda order_id, _segment="CASH": {"order_id": order_id, "status": "CANCELLED"})

    orders = broker.get_open_orders(segment="CASH")
    assert isinstance(orders, list)
    assert orders[0]["order_id"] == "OID1"

    result = broker.cancel_order("OID1", segment="CASH")
    assert result is not None
    assert result["status"] == "CANCELLED"


def test_broker_cancel_order_handles_missing_client_support(monkeypatch):
    broker = BrokerInterface()

    class ClientWithoutCancel:
        def get_open_orders(self, segment="CASH"):
            _ = segment
            return [{"order_id": "OID1"}]

    monkeypatch.setattr(broker, "client", ClientWithoutCancel())
    assert broker.get_open_orders() == [{"order_id": "OID1"}]
    assert broker.cancel_order("OID1") is None


def test_http_provider_selection(monkeypatch):
    monkeypatch.setattr(Config, "BROKER_PROVIDER", "http", raising=False)
    monkeypatch.setattr(Config, "BROKER_BASE_URL", "https://broker.example.com", raising=False)
    monkeypatch.setattr(Config, "GROWW_API_KEY", "k", raising=False)
    monkeypatch.setattr(Config, "GROWW_API_SECRET", "s", raising=False)

    broker = BrokerInterface()
    assert broker.provider == "http"
    assert broker.client.__class__.__name__ == "HttpBrokerClient"


def test_groww_provider_selection(monkeypatch):
    monkeypatch.setattr(Config, "BROKER_PROVIDER", "groww", raising=False)
    monkeypatch.setattr(Config, "BROKER_BASE_URL", "", raising=False)
    monkeypatch.setattr(Config, "GROWW_API_KEY", "k", raising=False)
    monkeypatch.setattr(Config, "GROWW_API_SECRET", "s", raising=False)
    monkeypatch.setattr(Config, "GROWW_TOKEN_MODE", "approval", raising=False)

    broker = BrokerInterface()
    assert broker.provider == "groww"
    assert broker.client.__class__.__name__ == "GrowwHttpClient"


def test_groww_client_approval_auth_and_contract(monkeypatch):
    class FakeResponse:
        def __init__(self, data: dict[str, Any], status_code: int = 200):
            self._data = data
            self.status_code = status_code

        def json(self) -> dict[str, Any]:
            return self._data

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

    class FakeSession:
        def __init__(self):
            self.headers: dict[str, str] = {}
            self.calls: list[tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]] = []

        def post(
            self,
            url: str,
            json: dict[str, Any] | None = None,
            headers: dict[str, str] | None = None,
            timeout: int = 0,
        ) -> FakeResponse:
            _ = timeout
            self.calls.append(("POST", url, json, headers))
            assert headers is not None
            assert headers["Authorization"] == "Bearer USER_API_KEY"
            assert json is not None
            assert json["key_type"] == "approval"
            assert "checksum" in json
            assert "timestamp" in json
            return FakeResponse(
                {
                    "status": "SUCCESS",
                    "payload": {"access_token": "ACCESS_TOKEN"},
                }
            )

        def request(
            self,
            method: str,
            url: str,
            json: dict[str, Any] | None = None,
            params: dict[str, Any] | None = None,
            timeout: int = 0,
        ) -> FakeResponse:
            _ = timeout
            self.calls.append((method, url, json, params))
            if method == "POST" and url.endswith("/v1/order/create"):
                assert json is not None
                assert json["trading_symbol"] == "RELIANCE"
                if json["transaction_type"] == "BUY":
                    assert json["order_type"] == "MARKET"
                    return FakeResponse(
                        {
                            "status": "SUCCESS",
                            "payload": {"order_id": "OID123", "order_status": "OPEN"},
                        }
                    )
                if json["transaction_type"] == "SELL":
                    assert json["order_type"] == "SL_M"
                    assert json["trigger_price"] == 2490.0
                    return FakeResponse(
                        {
                            "status": "SUCCESS",
                            "payload": {"order_id": "OID124", "order_status": "OPEN"},
                        }
                    )
                return FakeResponse(
                    {
                        "status": "FAILURE",
                        "error": {"message": "unsupported transaction_type"},
                    },
                    status_code=400,
                )
            if method == "GET" and "/v1/order/status/" in url:
                assert params == {"segment": "CASH"}
                return FakeResponse(
                    {
                        "status": "SUCCESS",
                        "payload": {"order_status": "EXECUTED"},
                    }
                )
            if method == "GET" and url.endswith("/v1/positions/user"):
                assert params == {"segment": "CASH"}
                return FakeResponse(
                    {
                        "status": "SUCCESS",
                        "payload": {
                            "positions": [
                                {
                                    "trading_symbol": "RELIANCE",
                                    "quantity": "5",
                                    "average_price": "2500.50",
                                    "pnl": "125.0",
                                }
                            ]
                        },
                    }
                )
            if method == "GET" and url.endswith("/v1/margins/detail/user"):
                return FakeResponse(
                    {
                        "status": "SUCCESS",
                        "payload": {"clear_cash": "10000.25", "collateral_amount": "5000.0"},
                    }
                )
            if method == "GET" and url.endswith("/v1/order/list"):
                assert params == {"segment": "CASH", "page": 0, "page_size": 100}
                return FakeResponse(
                    {
                        "status": "SUCCESS",
                        "payload": {
                            "order_list": [
                                {
                                    "groww_order_id": "GOID123",
                                    "order_reference_id": "REF123",
                                    "trading_symbol": "RELIANCE",
                                    "quantity": "5",
                                    "order_status": "OPEN",
                                },
                                {
                                    "groww_order_id": "GOID124",
                                    "order_status": "CANCELLED",
                                },
                            ]
                        },
                    }
                )
            if method == "POST" and url.endswith("/v1/order/cancel"):
                assert json is not None
                assert json.get("segment") == "CASH"
                assert json.get("groww_order_id") == "GOID123" or json.get("order_id") == "GOID123"
                return FakeResponse(
                    {
                        "status": "SUCCESS",
                        "payload": {"groww_order_id": "GOID123", "order_status": "CANCELLED"},
                    }
                )
            return FakeResponse({"status": "FAILURE", "error": {"message": "unknown"}}, status_code=404)

    monkeypatch.setattr(broker_mod.requests, "Session", FakeSession)

    client = broker_mod.GrowwHttpClient(
        api_key="USER_API_KEY",
        api_secret="USER_API_SECRET",
        token_mode="approval",
        base_url="https://api.groww.in",
    )

    assert client.authenticate() is True
    assert client.session.headers["Authorization"] == "Bearer ACCESS_TOKEN"

    order = client.place_order("RELIANCE", 5, "BUY")
    assert order["order_id"] == "OID123"
    assert order["status"] == "OPEN"

    stop_order = client.place_order("RELIANCE", 5, "SELL_STOP_LOSS", price=2490.0)
    assert stop_order["order_id"] == "OID124"
    assert stop_order["status"] == "OPEN"

    assert client.get_order_status("OID123") == "COMPLETE"

    positions = client.get_positions()
    assert positions[0]["symbol"] == "RELIANCE"
    assert positions[0]["quantity"] == 5
    assert positions[0]["average_price"] == 2500.5

    funds = client.get_funds()
    assert funds["cash"] == 10000.25
    assert funds["collateral"] == 5000.0

    open_orders = client.get_open_orders("CASH")
    assert len(open_orders) == 1
    assert open_orders[0]["order_id"] == "GOID123"
    assert open_orders[0]["status"] == "OPEN"

    cancel_result = client.cancel_order("GOID123", "CASH")
    assert cancel_result["order_id"] == "GOID123"
    assert cancel_result["status"] == "CANCELLED"


def test_groww_historical_candles_falls_back_to_legacy_endpoint(monkeypatch):
    class FakeResponse:
        def __init__(self, data: dict[str, Any], status_code: int = 200):
            self._data = data
            self.status_code = status_code

        def json(self) -> dict[str, Any]:
            return self._data

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

    class FakeSession:
        def __init__(self):
            self.headers: dict[str, str] = {}
            self.calls: list[tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]] = []

        def request(
            self,
            method: str,
            url: str,
            json: dict[str, Any] | None = None,
            params: dict[str, Any] | None = None,
            timeout: int = 0,
        ) -> FakeResponse:
            _ = timeout
            self.calls.append((method, url, json, params))
            if method == "GET" and url.endswith("/v1/historical/candles"):
                return FakeResponse(
                    {"status": "FAILURE", "error": {"message": "forbidden"}},
                    status_code=403,
                )
            if method == "GET" and url.endswith("/v1/historical/candle/range"):
                assert params is not None
                assert params["exchange"] == "NSE"
                assert params["segment"] == "CASH"
                assert params["trading_symbol"] == "RELIANCE"
                assert params["interval_in_minutes"] == 1440
                return FakeResponse(
                    {
                        "status": "SUCCESS",
                        "payload": {
                            "candles": [
                                [1764527400, 1575.0, 1577.5, 1563.6, 1566.1, 8920233],
                            ]
                        },
                    }
                )
            return FakeResponse({"status": "FAILURE", "error": {"message": "unknown"}}, status_code=404)

    monkeypatch.setattr(broker_mod.requests, "Session", FakeSession)

    client = broker_mod.GrowwHttpClient(
        api_key="ACCESS_TOKEN_DIRECT",
        api_secret="",
        token_mode="access_token",
        base_url="https://api.groww.in",
    )
    assert client.authenticate() is True

    candles = client.get_historical_candles(
        exchange="NSE",
        segment="CASH",
        groww_symbol="NSE-RELIANCE",
        start_time="2025-12-01 09:15:00",
        end_time="2025-12-15 15:30:00",
        candle_interval="1day",
    )
    assert candles == [[1764527400, 1575.0, 1577.5, 1563.6, 1566.1, 8920233]]

    paths = [url.rsplit("https://api.groww.in", 1)[-1] for _, url, _, _ in client.session.calls]
    assert "/v1/historical/candles" in paths
    assert "/v1/historical/candle/range" in paths
