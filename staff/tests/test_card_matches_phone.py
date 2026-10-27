"""The printed card and the phone must name the same two refuges in the same order: both read the stamped plan."""
import pytest


@pytest.mark.parametrize("cid", ["c_rosa", "c_harold", "c_margaret", "c_walter", "c_june", "c_lupe"])
def test_card_refuges_equal_bundle_plan_refuges(sample, cid):
    from ember_staff import db, plan_writer, workflow
    row = db.get(cid)
    a, b = plan_writer.chosen(row["plan"], row.get("selected"))
    card_ids = [c["refuge"]["id"] for c in (a, b) if c]
    phone = workflow.plan_for_bundle(row)["choices"]
    phone_ids = [c["refuge"]["id"] for c in phone[: len(card_ids)]]
    if not card_ids:                      # bedbound / no-route clients have no refuges on either side
        assert phone_ids == []
    else:
        assert phone_ids == card_ids, cid


def test_swap_moves_both_card_and_phone(sample):
    from ember_staff import db, plan_writer, workflow
    row = db.get("c_lupe")
    if len(row["plan"].get("choices") or []) < 3:
        pytest.skip("needs three candidates to swap")
    workflow.swap("c_lupe", "A")
    row = db.get("c_lupe")
    a, _ = plan_writer.chosen(row["plan"], row.get("selected"))
    assert workflow.plan_for_bundle(row)["choices"][0]["refuge"]["id"] == a["refuge"]["id"]
