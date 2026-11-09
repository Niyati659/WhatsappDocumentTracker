import os
import sys
import time

from google.genai import errors

for name in [k for k in os.environ if k.startswith("GEMINI_API_KEY")]:
    del os.environ[name]

from app import classify

failures = []


def check(label, actual, expected):
    ok = actual == expected
    print(f"{'PASS' if ok else 'FAIL'}  {label}: got {actual!r}, expected {expected!r}")
    if not ok:
        failures.append(label)


def limit_error(message):
    return errors.ClientError(429, {"error": {"code": 429, "message": message}})


def reset():
    classify._cooldown_until.clear()


os.environ["GEMINI_API_KEY"] = "key-a"
os.environ["GEMINI_API_KEY_2"] = "key-b"
os.environ["GEMINI_API_KEYS"] = "key-c, key-a ,"
check("keys are collected, deduplicated, in order", classify._gemini_keys(), ["key-a", "key-b", "key-c"])
os.environ["GEMINI_API_KEY3"] = "key-d"
check("names without an underscore also work", classify._gemini_keys(), ["key-a", "key-b", "key-d", "key-c"])
del os.environ["GEMINI_API_KEY3"]

calls = []


def fake_daily_limit_on_a(key, model, data, mime):
    calls.append((key, model))
    if key == "key-a":
        raise limit_error("Quota exceeded: requests per day limit")
    return f"answer-from-{key}"


classify._call_gemini = fake_daily_limit_on_a
reset()
check("falls over to the next key when one is limited", classify._gemini_generate(b"x", "image/jpeg"), "answer-from-key-b")
check("tried key-a's models once each before moving on", [c for c in calls if c[0] == "key-a"], [("key-a", m) for m in classify.MODELS])

calls.clear()
check("a limited key is skipped on the next request", classify._gemini_generate(b"x", "image/jpeg"), "answer-from-key-b")
check("key-a was not retried", [c for c in calls if c[0] == "key-a"], [])


def fake_all_limited(key, model, data, mime):
    raise limit_error("Quota exceeded: requests per day limit")


classify._call_gemini = fake_all_limited
reset()
try:
    classify._gemini_generate(b"x", "image/jpeg")
    outcome = "no error"
except errors.ClientError:
    outcome = "raised the rate limit error"
check("raises when every key is limited", outcome, "raised the rate limit error")

attempts = []


def fake_flaky(key, model, data, mime):
    attempts.append(1)
    if len(attempts) == 1:
        raise errors.ServerError(503, {"error": {"code": 503, "message": "busy"}})
    return "recovered"


classify._call_gemini = fake_flaky
reset()
time.sleep(0)
orig_sleep = time.sleep
time.sleep = lambda s: None
check("retries a temporary server error", classify._gemini_generate(b"x", "image/jpeg"), "recovered")
time.sleep = orig_sleep


def fake_bad_request(key, model, data, mime):
    raise errors.ClientError(400, {"error": {"code": 400, "message": "bad"}})


classify._call_gemini = fake_bad_request
reset()
try:
    classify._gemini_generate(b"x", "image/jpeg")
    outcome = "no error"
except errors.ClientError as exc:
    outcome = f"raised {exc.code}"
check("does not rotate on a real error like 400", outcome, "raised 400")

for name in [k for k in os.environ if k.startswith("GEMINI_API_KEY")]:
    del os.environ[name]
try:
    classify._gemini_keys()
    outcome = "no error"
except KeyError:
    outcome = "KeyError"
check("no keys configured is reported clearly", outcome, "KeyError")

print(f"\n{'ALL PASSED' if not failures else 'FAILED: ' + ', '.join(failures)}")
sys.exit(1 if failures else 0)
