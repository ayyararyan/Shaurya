# ruff: noqa: F821
# EVOLVE-BLOCK-START
def alpha_score(
    ret_1,
    ret_5,
    ret_15,
    ret_30,
    ret_60,
    rv_5,
    rv_15,
    rv_30,
    rv_60,
    session_return,
    overnight_gap,
    elapsed_fraction,
    time_sin,
    time_cos,
):
    """Return a causal cross-time score; the evaluator converts its tails to positions."""
    return np.tanh(overnight_gap) * np.where(rv_30 < 1.0, 1.0, 0.5)


# EVOLVE-BLOCK-END
