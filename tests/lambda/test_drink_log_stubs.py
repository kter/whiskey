from tests.lambda_module_loader import load_lambda_module


analyze = load_lambda_module("drink_log_analyze_stub_tests", "lambda/drink-log-analyze/index.py")
places = load_lambda_module("drink_log_places_stub_tests", "lambda/drink-log-analyze/places.py")


def test_task08_handlers_replace_the_501_stubs():
    assert callable(analyze.lambda_handler)
    assert callable(places.lambda_handler)
    assert "placeholder" not in (analyze.__doc__ or "").lower()
    assert "placeholder" not in (places.__doc__ or "").lower()
