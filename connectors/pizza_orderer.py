from typing import Any, Dict, Optional
import os

try:
    from pizzapi import Address, Customer, Order, PaymentObject  # type: ignore
except ImportError:
    Address = Customer = Order = PaymentObject = None  # type: ignore


class PizzaOrderer:
    """Thin wrapper around the Domino's helper library."""

    def __init__(self, cfg: Optional[Dict[str, Any]] = None, llm=None) -> None:
        self.cfg = cfg or {}
        self.llm = llm
        raw_live = self.cfg.get("live_mode", os.environ.get("PIZZA_LIVE_MODE", "false"))
        if isinstance(raw_live, str):
            raw_live = raw_live.strip().strip('"').strip("'")
        self.live_mode = str(raw_live).lower() in {"1", "true", "yes", "on"}

    def _ready(self) -> bool:
        return all(obj is not None for obj in (Address, Customer, Order, PaymentObject))

    def _check_live(self) -> Optional[Dict[str, str]]:
        if self.live_mode:
            return None
        return {
            "status": "disabled",
            "error": "Live pizza ordering is switched off. Set PIZZA_LIVE_MODE=true when you are ready.",
        }

    def _validate(self, data: Dict[str, Any]) -> Optional[Dict[str, str]]:
        for key in ("customer", "address", "items"):
            if key not in data:
                return {"status": "failed", "error": f"Missing {key} details for the order."}

        customer = data["customer"]
        address = data["address"]
        items = data["items"]

        cust_required = {"first_name", "last_name", "email", "phone"}
        addr_required = {"street", "city", "region", "postal_code"}

        missing_customer = cust_required - set(customer.keys())
        missing_address = addr_required - set(address.keys())

        if missing_customer:
            return {
                "status": "failed",
                "error": f"Customer details missing: {', '.join(sorted(missing_customer))}.",
            }
        if missing_address:
            return {
                "status": "failed",
                "error": f"Address details missing: {', '.join(sorted(missing_address))}.",
            }
        if not items:
            return {"status": "failed", "error": "Add at least one Domino's menu code to items."}
        return None

    def _build_payment(self, data: Dict[str, Any]) -> Optional[PaymentObject]:
        payment = data.get("payment") or {}
        number = payment.get("card_number") or os.environ.get("PIZZA_CARD_NUMBER")
        exp = payment.get("card_expiration") or os.environ.get("PIZZA_CARD_EXPIRATION")
        cvv = payment.get("card_cvv") or os.environ.get("PIZZA_CARD_CVV")
        postal = payment.get("billing_postal_code") or os.environ.get("PIZZA_BILLING_POSTAL_CODE")

        if not all([number, exp, cvv, postal]):
            return None

        return PaymentObject(number, exp, cvv, postal)  # type: ignore[arg-type]

    def _scrub(self, data: Dict[str, Any]) -> None:
        if not self.llm:
            return
        notes = data.get("special_instructions")
        if isinstance(notes, str):
            data["special_instructions"] = self.llm._redact_sensitive_info(notes)

    def place_order(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self._ready():
            return {
                "status": "failed",
                "error": "pizzapi package is not installed.",
            }

        disabled = self._check_live()
        if disabled:
            return disabled

        validation_error = self._validate(payload)
        if validation_error:
            return validation_error

        self._scrub(payload)

        customer_info = payload["customer"]
        address_info = payload["address"]
        items = payload["items"]

        address = Address(
            address_info["street"],
            address_info["city"],
            address_info["region"],
            address_info["postal_code"],
        )

        store = address.closest_store()
        if not store:
            return {"status": "failed", "error": "Could not locate a Domino's store for that address."}

        customer = Customer(
            customer_info["first_name"],
            customer_info["last_name"],
            customer_info["email"],
            customer_info["phone"],
        )

        order = Order(store, customer, address)
        normalized_items = []
        for item in items:
            code_raw = (item.get("code") or "").strip()
            quantity = max(1, int(item.get("quantity", 1)))
            if not code_raw:
                return {"status": "failed", "error": "Each item needs a Domino's menu or coupon code."}

            base_code = code_raw.split()[0]
            normalized_items.append({**item, "code": base_code, "quantity": quantity})

            try:
                if base_code.isdigit():
                    order.add_coupon(base_code)
                else:
                    for _ in range(quantity):
                        order.add_item(base_code)
            except Exception:
                return {
                    "status": "failed",
                    "error": f"Domino's did not recognize the code '{base_code}'. Please confirm it in the Domino's menu or coupon list.",
                }

        price_info = order.validate()
        order_summary = price_info.get("Order", {})
        amount_info = order_summary.get("Amounts", {})
        total = amount_info.get("Customer")

        payment_object = self._build_payment(payload)
        if not payment_object:
            return {
                "status": "preview",
                "store_id": store.store_id,
                "total": total,
                "currency": "USD",
                "items": normalized_items,
                "message": "Payment info missing. Add card details or set environment variables to place the order.",
            }

        result = order.place(payment_object)
        return {
            "status": "ordered",
            "store_id": store.store_id,
            "confirmation": result.get("Order", {}).get("OrderID"),
            "total": total,
            "currency": "USD",
            "items": normalized_items,
            "estimates": result.get("Status", {}),
        }
