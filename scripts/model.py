"""The Plackett-Luce direct model (locked decision 11).

Each driver in a race gets a strength: a linear function of their features.
The probability the race finishes in a given order is built position by
position: P(win) is softmax over all strengths, then the winner is removed
and the same rule gives P(second), and so on. Because a race is modelled as
one ranking, the probabilities are coherent by construction: win
probabilities sum to 1 and exactly one driver takes each position.

Fitting maximises the likelihood of the observed finishing orders over the
feature weights, with scipy. Features are z-scored on the training data and
missing values become 0 after scaling, which means "field average".

Run the self-check:

    conda run -n gridcast python scripts/model.py
"""

import numpy as np
from scipy.optimize import minimize


def log_softmax_first(scores: np.ndarray) -> float:
    """log P(the first entry beats the rest) under softmax, stable."""
    m = scores.max()
    return scores[0] - (m + np.log(np.exp(scores - m).sum()))


def negative_log_likelihood(beta, race_features, race_orders) -> float:
    total = 0.0
    for X, order in zip(race_features, race_orders):
        strengths = X @ beta
        for j in range(len(order) - 1):
            remaining = order[j:]
            total -= log_softmax_first(strengths[remaining])
    return total


def fit(race_features: list[np.ndarray], race_orders: list[np.ndarray]) -> dict:
    """Fit weights on training races.

    race_features: one (n_drivers, n_features) array per race, raw units.
    race_orders: one array of driver row indices per race, finish order.
    Returns the weights plus the scaler needed to predict on the same terms.
    """
    stacked = np.vstack(race_features)
    mean = np.nanmean(stacked, axis=0)
    std = np.nanstd(stacked, axis=0)
    std[std == 0] = 1.0

    scaled = [scale_features(X, mean, std) for X in race_features]
    n_features = stacked.shape[1]
    result = minimize(
        negative_log_likelihood,
        x0=np.zeros(n_features),
        args=(scaled, race_orders),
        method="BFGS",
    )
    return {"beta": result.x, "mean": mean, "std": std, "nll": result.fun}


def scale_features(X: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    scaled = (X - mean) / std
    return np.nan_to_num(scaled, nan=0.0)


def strengths(model: dict, X: np.ndarray) -> np.ndarray:
    return scale_features(X, model["mean"], model["std"]) @ model["beta"]


def sample_position_matrix(strengths: np.ndarray, n_samples: int = 5000, seed: int = 0) -> np.ndarray:
    """P(driver, position) by sampling full finishing orders.

    Sampling follows the model's own definition: pick the winner with softmax
    probability, remove them, repeat. matrix[i, k] is P(driver i finishes in
    position k+1), each row and each column sums to 1.
    """
    # ponytail: plain sequential sampling, a few seconds per race; vectorise
    # with the Gumbel trick only if backtests get slow.
    rng = np.random.default_rng(seed)
    n = len(strengths)
    counts = np.zeros((n, n))
    for _ in range(n_samples):
        remaining = list(range(n))
        for pos in range(n):
            scores = strengths[remaining]
            scores = scores - scores.max()
            p = np.exp(scores)
            p /= p.sum()
            pick = rng.choice(len(remaining), p=p)
            counts[remaining[pick], pos] += 1
            remaining.pop(pick)
    return counts / n_samples


def demo() -> None:
    """Self-check on synthetic races where the truth is known."""
    rng = np.random.default_rng(1)
    true_beta = np.array([-1.0])  # one feature, bigger value means slower
    races, orders = [], []
    for _ in range(30):
        X = rng.normal(size=(6, 1))
        s = X @ true_beta + rng.gumbel(size=6)  # Gumbel noise draws a PL order
        order = np.argsort(-s)
        races.append(X)
        orders.append(order)

    model = fit(races, orders)
    assert model["beta"][0] < 0, "weight should be negative like the truth"

    X = np.array([[-1.0], [0.0], [1.0]])
    matrix = sample_position_matrix(strengths(model, X), n_samples=4000)
    assert matrix[0, 0] > matrix[2, 0], "faster driver must win more often"
    assert abs(matrix[:, 0].sum() - 1.0) < 1e-9, "win probabilities must sum to 1"
    print(f"self-check passed, fitted weight {model['beta'][0]:.2f} (true -1.0)")


if __name__ == "__main__":
    demo()
