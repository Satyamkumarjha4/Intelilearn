from llm_registry.params import to_integration_kwargs, validate_params


def test_valid_params_pass():
    assert validate_params("google_genai", {"temperature": 0.4, "top_k": 40, "max_tokens": 1000, "stop": ["END"]}) == []


def test_unknown_param_for_provider_is_rejected():
    problems = validate_params("groq", {"top_p": 0.9})
    assert problems and "not supported" in problems[0]


def test_type_errors_are_reported():
    problems = validate_params("openai", {"temperature": "hot", "max_tokens": -1, "stop": "END"})
    assert len(problems) == 3


def test_params_must_be_an_object():
    assert validate_params("openai", [1, 2])


def test_ollama_renames_max_tokens():
    assert to_integration_kwargs("ollama", {"max_tokens": 500, "temperature": 0.1}) == {
        "num_predict": 500,
        "temperature": 0.1,
    }
