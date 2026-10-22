from meta_agent.activity_log import normalize_activity, object_type_to_level


def test_legacy_object_type_mapping():
    assert object_type_to_level("CAMPAIGN_GROUP") == "campaign"
    assert object_type_to_level("CAMPAIGN") == "adset"      # legacy: old "campaign" == ad set
    assert object_type_to_level("ADGROUP") == "ad"          # legacy: old "ad group" == ad
    assert object_type_to_level("ACCOUNT") == "account"
    assert object_type_to_level("AD_SET") == "adset"        # modern name
    assert object_type_to_level("WAT") == "other"


def _activity(old_url_token):
    return {
        "event_time": "2026-08-20T17:15:09+0000",
        "event_type": "update_ad_creative",
        "object_id": "120256352117080771",
        "object_type": "ADGROUP",
        "object_name": "NUTRISULIN BROAD STATIC",
        "actor_id": "101", "actor_name": "Manindra",
        "extra_data": ('{"old_value":["https://scontent.fbcdn.net/v/t15/img.jpg'
                       f'?_nc_ohc={old_url_token}&ccb=1-7"],"type":"creative"}}'),
    }


def test_dedupe_key_stable_across_resigned_cdn_urls():
    # Meta re-signs CDN image URLs each call; the same event must dedupe to one key.
    a = normalize_activity(_activity("AAAA"))
    b = normalize_activity(_activity("ZZZZ"))   # only the volatile url token differs
    assert a["dedupe_key"] == b["dedupe_key"]


def test_dedupe_key_differs_on_real_change():
    base = {
        "event_time": "2026-08-20T17:49:30+0000", "event_type": "update_ad_run_status",
        "object_id": "1", "object_type": "ADGROUP", "actor_id": "101", "actor_name": "Nalin",
    }
    a = normalize_activity({**base, "extra_data": '{"old_value":"Active","new_value":"Paused","type":"run_status"}'})
    b = normalize_activity({**base, "extra_data": '{"old_value":"Active","new_value":"Inactive","type":"run_status"}'})
    assert a["dedupe_key"] != b["dedupe_key"]


def test_manual_vs_automated_actor():
    manual = normalize_activity({"event_time": "t", "event_type": "e", "object_id": "1",
                                 "object_type": "ADGROUP", "actor_name": "Manindra", "extra_data": "{}"})
    auto = normalize_activity({"event_time": "t", "event_type": "e", "object_id": "1",
                               "object_type": "ADGROUP", "actor_name": "Meta", "extra_data": "{}"})
    assert manual["is_manual"] is True
    assert auto["is_manual"] is False
    assert manual["level"] == "ad"
