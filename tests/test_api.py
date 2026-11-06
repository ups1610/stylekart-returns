"""One test (or more) per seed scenario in the plan, plus the critical gates."""

from datetime import datetime

from app import clock
from app.seed import reset_data

ANANYA = "+919000000001"
ROHAN = "+919000000002"
DEV = "+919000000008"


def slot_ids(client, order_id):
    return [s["slot_id"] for s in client.get(f"/pickup-slots/{order_id}").json()["slots"]]


def book(client, order_id, item_id, reason="size issue", slot=None, **extra):
    slot = slot or slot_ids(client, order_id)[0]
    return client.post("/returns", json={"order_id": order_id, "item_id": item_id,
                                         "reason": reason, "slot_id": slot, **extra})


# ---------------------------------------------------------------- health

def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


# ---------------------------------------------------------------- lookup

def test_lookup_normalises_phone_formats(client):
    for raw in ["+91 90000 00001", "09000000001", "9000000001", "919000000001"]:
        body = client.get(f"/customers/by-phone/{raw}").json()
        assert body["found"] and body["first_name"] == "Ananya", raw


def test_unregistered_number(client):
    body = client.get("/customers/by-phone/+919999999999").json()
    assert body["found"] is False
    assert "registered mobile number" in body["say"]


def test_rohan_has_several_items_newest_first(client):
    body = client.get(f"/customers/by-phone/{ROHAN}").json()
    names = [i["item_name"] for i in body["items"]]
    assert names[:3] == ["white running sneakers", "black slim-fit jeans", "checked casual shirt"]
    assert body["item_count"] == 4


def test_multi_item_order_lists_both_items(client):
    body = client.get("/customers/by-phone/+919000000003").json()
    assert {i["item_id"] for i in body["items"]} == {"SK1006-1", "SK1006-2"}


# ---------------------------------------------------------------- eligibility rules

def elig(client, order_id, item_id, **extra):
    return client.post("/returns/eligibility", json={"order_id": order_id, "item_id": item_id, **extra})


def test_happy_path_eligible(client):
    body = elig(client, "SK1001", "SK1001-1").json()
    assert body["eligible"] and body["reason_code"] == "OK" and body["days_left"] == 11


def test_window_expired_by_three_days(client):
    body = elig(client, "SK1007", "SK1007-1").json()
    assert not body["eligible"] and body["reason_code"] == "WINDOW_EXPIRED" and body["days_past"] == 3


def test_day_14_is_last_eligible_day(client):
    body = elig(client, "SK1008", "SK1008-1").json()
    assert body["eligible"] and body["days_left"] == 0
    assert "aakhri din" in body["say"]


def test_non_returnable_category(client):
    assert elig(client, "SK1009", "SK1009-1").json()["reason_code"] == "NON_RETURNABLE"


def test_not_delivered(client):
    assert elig(client, "SK1010", "SK1010-1").json()["reason_code"] == "NOT_DELIVERED"


def test_already_returned_reads_back_id(client):
    body = elig(client, "SK1011", "SK1011-1").json()
    assert body["reason_code"] == "ALREADY_RETURNED"
    assert "R T 4 0 0 1 1" in body["say"]


def test_item_from_wrong_order_is_404(client):
    assert elig(client, "SK1001", "SK1003-1").status_code == 404


def test_other_customers_order_is_403(client):
    r = elig(client, "SK1003", "SK1003-1", phone=ANANYA)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "NOT_OWNER"


def test_eligibility_api_failure_scenario(client):
    r = elig(client, "SK1014", "SK1014-1")
    assert r.status_code == 500 and r.json()["detail"]["code"] == "UPSTREAM_ERROR"


# ---------------------------------------------------------------- pickup slots

def test_slots_at_10am_skip_this_morning(client):
    body = client.get("/pickup-slots/SK1001").json()
    ids = [s["slot_id"] for s in body["slots"]]
    assert "2026-11-06_morning" not in ids
    assert ids[0] == "2026-11-06_afternoon"
    assert body["slots"][0]["slot_text"] == "aaj dopahar 12 se 4 baje"
    assert len(ids) == 6


def test_late_night_call_offers_only_future_days(client):
    clock.freeze(datetime(2026, 11, 6, 23, 50))
    ids = slot_ids(client, "SK1001")
    assert all(not i.startswith("2026-11-06") for i in ids)
    assert ids[0] == "2026-11-07_morning"


def test_no_pickup_pincode(client):
    body = client.get("/pickup-slots/SK1013").json()
    assert body["slots_available"] is False and body["slots"] == []


# ---------------------------------------------------------------- create return

def test_happy_path_creates_one_return(client):
    r = book(client, "SK1001", "SK1001-1", phone=ANANYA)
    body = r.json()
    assert r.status_code == 200 and body["already_existed"] is False
    assert body["return_id_spoken"].startswith("R T")
    assert body["cod_sms_sent"] is False
    state = client.get(f"/admin/state/{ANANYA}").json()
    assert len(state["returns"]) == 1 and state["returns"][0]["reason"] == "size issue"


def test_repeat_create_is_idempotent(client):
    first = book(client, "SK1001", "SK1001-1").json()
    second = book(client, "SK1001", "SK1001-1").json()
    assert second["return_id"] == first["return_id"] and second["already_existed"] is True
    assert len(client.get(f"/admin/state/{ANANYA}").json()["returns"]) == 1


def test_slow_create_retry_never_duplicates(client):
    first = book(client, "SK1015", "SK1015-1").json()
    second = book(client, "SK1015", "SK1015-1").json()
    assert first["return_id"] == second["return_id"]


def test_one_item_of_multi_item_order(client):
    book(client, "SK1006", "SK1006-2", reason="did not like")
    state = client.get("/admin/state/+919000000003").json()
    assert [r["item_id"] for r in state["returns"]] == ["SK1006-2"]
    assert elig(client, "SK1006", "SK1006-1").json()["eligible"] is True


def test_critical_gate_blocks_ineligible_create(client):
    for order, item, code in [("SK1007", "SK1007-1", "WINDOW_EXPIRED"),
                              ("SK1009", "SK1009-1", "NON_RETURNABLE"),
                              ("SK1010", "SK1010-1", "NOT_DELIVERED")]:
        r = client.post("/returns", json={"order_id": order, "item_id": item,
                                          "reason": "favour please", "slot_id": "2026-11-07_morning"})
        assert r.status_code == 409 and r.json()["detail"]["code"] == code
    assert len(client.get("/admin/state/+919000000004").json()["returns"]) == 0


def test_unavailable_slot_rejected_with_options(client):
    r = client.post("/returns", json={"order_id": "SK1001", "item_id": "SK1001-1",
                                      "reason": "size", "slot_id": "2026-11-06_morning"})
    assert r.status_code == 422
    assert r.json()["detail"]["available_slots"]


def test_cod_order_sends_sms_link(client):
    body = book(client, "SK1012", "SK1012-1").json()
    assert body["cod_sms_sent"] is True and "bank details" in body["refund_eta_text"]


# ---------------------------------------------------------------- tickets, callbacks, refunds

def test_quality_ticket_for_damaged_expired_item(client):
    body = client.post("/quality-tickets", json={"order_id": "SK1007", "item_id": "SK1007-1",
                                                 "issue": "zip broken"}).json()
    assert body["ticket_id"].startswith("QT") and body["photo_link_sms_sent"]


def test_callback(client):
    body = client.post("/callbacks", json={"phone": "9000000010", "topic": "no pickup slots",
                                           "preferred_time": "kal subah"}).json()
    assert body["callback_id"].startswith("CB") and "kal subah" in body["say"]
    tickets = client.get("/admin/state/+919000000010").json()["tickets"]
    assert len(tickets) == 1


def test_refund_status_variants(client):
    assert client.get("/refunds/SK1001").json()["has_return"] is False
    assert "pickup" in client.get("/refunds/SK1011").json()["say"]
    assert "refund ho chuka" in client.get("/refunds/SK1005").json()["say"]


# ---------------------------------------------------------------- admin

def test_real_numbers_are_seeded(client):
    for phone, name in [("7505062257", "Upendra Singh"), ("+91 99532 60051", "Anant Jakhmola"),
                        ("09149262211", "Rishabh Thakur")]:
        body = client.get(f"/customers/by-phone/{phone}").json()
        assert body["found"] and body["full_name"] == name, phone


def test_upendra_has_returnable_expired_and_nonreturnable(client):
    codes = {item: elig(client, item.split("-")[0], item).json()["reason_code"]
             for item in ["SK1016-1", "SK1017-1", "SK1018-1"]}
    assert codes == {"SK1016-1": "OK", "SK1017-1": "WINDOW_EXPIRED", "SK1018-1": "NON_RETURNABLE"}


def test_anant_cod_and_in_transit(client):
    assert book(client, "SK1019", "SK1019-1").json()["cod_sms_sent"] is True
    assert elig(client, "SK1020", "SK1020-1").json()["reason_code"] == "NOT_DELIVERED"


def test_rishabh_multi_item_and_refund_status(client):
    book(client, "SK1021", "SK1021-2")
    assert elig(client, "SK1021", "SK1021-1").json()["eligible"] is True
    assert "refund ho chuka" in client.get("/refunds/SK1022").json()["say"]


def test_map_phone_points_number_at_seed_customer(client):
    me = "+917505062257"
    client.post("/admin/map-phone", json={"phone": me, "customer_id": "C04"})
    assert client.get(f"/customers/by-phone/{me}").json()["first_name"] == "Meera"
    client.post("/admin/map-phone", json={"phone": me, "customer_id": "C02"})
    assert client.get(f"/customers/by-phone/{me}").json()["first_name"] == "Rohan"


def test_reset_restores_seed(client):
    book(client, "SK1001", "SK1001-1")
    client.post("/admin/reset")
    assert client.get(f"/admin/state/{ANANYA}").json()["returns"] == []


def test_events_are_logged(client):
    elig(client, "SK1001", "SK1001-1")
    events = client.get("/admin/events").json()["events"]
    assert events[0]["endpoint"] == "POST /returns/eligibility" and events[0]["status"] == 200


def test_seed_dates_follow_frozen_clock(client):
    clock.freeze(datetime(2026, 12, 25, 9, 0))
    reset_data()
    body = elig(client, "SK1008", "SK1008-1").json()
    assert body["eligible"] and body["days_left"] == 0
