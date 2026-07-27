"""
rules.py
--------
Rule-based fraud detection: a transparent, auditable set of threshold
rules an ops team can read and defend, independent of any ML model - the
same kind of system many mobile money operators run today (see
baselines.py's module docstring). This is the SAME engine used in two
places, so there is never a second, independently-drifting implementation:

  - train.py's baseline comparison report ("how good is a pure rule
    system compared to XGBoost?"), via baselines.get_baseline_suite().
  - ensemble.py's live scoring, where the rule engine is one of three
    independent votes (alongside XGBoost and the two unsupervised
    detectors) folded into the final fraud_probability, and its verdict
    can also trigger prevention (see database/write_alerts_to_db.py).

Every rule reads the same feature columns feature_engineering.py /
online_features.py already compute, so it costs nothing extra to run
alongside the ML models - same features, one more, independent opinion.

Most cutoffs are PERCENTILES learned from the training population at fit
time, not hardcoded absolute numbers - see config.py's comment on
RULE_LEGACY_AMOUNT_PERCENTILE for why a fixed-constant rule engine doesn't
survive contact with a different dataset's currency scale or user count.
"""

import numpy as np
import pandas as pd

import config


class RuleEngine:
    """Learns a handful of percentile-based cutoffs from training data
    (fit), then evaluates a fixed set of named rules against them
    (evaluate). predict_proba_fraud/predict_flag give it the same
    interface as every other model in baselines.py, so train.py can treat
    it uniformly."""

    name = "Rule-Based Engine"

    def __init__(self):
        self.legacy_amount_cutoff = None
        self.large_amount_cutoff = None
        self.balance_error_cutoff = None
        self.fanin_ratio_cutoff = None
        self.fanin_min_incoming = None
        self.velocity_1h_cutoff = None
        self.velocity_6h_cutoff = None
        self.structuring_sum_cutoff = None

    def fit(self, X, y=None):
        self.legacy_amount_cutoff = float(np.percentile(X["amount"], config.RULE_LEGACY_AMOUNT_PERCENTILE))
        self.large_amount_cutoff = float(np.percentile(X["amount"], config.RULE_LARGE_AMOUNT_PERCENTILE))

        # PaySim-style sources (this project's synthetic generator included)
        # very commonly leave balance columns untouched/zeroed for whole
        # transaction types - sender_balance_delta == 0 despite a nonzero
        # amount means "sender's balance wasn't tracked for this row", not
        # "no money moved". Fitting the reconciliation cutoff (and
        # evaluating the two balance-integrity rules below) separately per
        # side, only on rows where that side's balance actually changed,
        # avoids treating that data-collection gap as a fraud signal.
        sender_tracked = self._sender_balance_tracked(X)
        receiver_tracked = self._receiver_balance_tracked(X)
        balance_errors = pd.concat([
            X.loc[sender_tracked, "sender_balance_error"].abs(),
            X.loc[receiver_tracked, "receiver_balance_error"].abs(),
        ])
        if balance_errors.empty:
            balance_errors = pd.concat([X["sender_balance_error"].abs(), X["receiver_balance_error"].abs()])
        self.balance_error_cutoff = max(
            float(np.percentile(balance_errors, config.RULE_BALANCE_ERROR_PERCENTILE)),
            config.RULE_BALANCE_ERROR_FLOOR,
        )

        self.fanin_ratio_cutoff = float(np.percentile(X["receiver_fanin_ratio"], config.RULE_FANIN_RATIO_PERCENTILE))
        self.fanin_min_incoming = float(np.percentile(X["receiver_incoming_count_so_far"], config.RULE_FANIN_MIN_INCOMING_PERCENTILE))

        self.velocity_1h_cutoff = max(
            float(np.percentile(X["user_txn_count_last_1"], config.RULE_VELOCITY_1H_PERCENTILE)),
            config.RULE_VELOCITY_MIN_COUNT,
        )
        # A 6h-window cutoff, fit the same way - structuring_pattern and
        # rapid_fanout_new_counterparty use this instead of the 1h cutoff
        # above: feeder.py's live simulation advances txn_step by exactly 1
        # per transaction (not per real hour), so a short burst of several
        # back-to-back transactions from one sender only reliably falls
        # inside each other's 6h window, not the much narrower 1h one.
        self.velocity_6h_cutoff = max(
            float(np.percentile(X["user_txn_count_last_6"], config.RULE_VELOCITY_1H_PERCENTILE)),
            config.RULE_VELOCITY_MIN_COUNT,
        )
        # Fit directly on the windowed SUM's own distribution rather than
        # reusing large_amount_cutoff (fit on individual amounts) - a sum
        # of several transactions is a different distribution than any one
        # of them, and reusing the single-transaction cutoff badly
        # under-shoots it, letting ordinary bursts of legitimate small
        # payments trip structuring_pattern.
        self.structuring_sum_cutoff = float(
            np.percentile(X["user_amount_sum_last_6"], config.RULE_LARGE_AMOUNT_PERCENTILE)
        )
        return self

    @staticmethod
    def _sender_balance_tracked(df):
        """True where the SENDER's balance columns actually moved - see
        the fit() comment above on why untouched (delta==0) balance
        columns must be excluded from the balance-integrity rules rather
        than treated as reconciliation failures. Sender and receiver are
        tracked independently: a receiver-side balance update tells us
        nothing about whether the sender's balance was recorded for this
        row, and vice versa."""
        return df["sender_balance_delta"] != 0

    @staticmethod
    def _receiver_balance_tracked(df):
        return df["receiver_balance_delta"] != 0

    def _rule_definitions(self):
        sender_tracked = self._sender_balance_tracked
        receiver_tracked = self._receiver_balance_tracked
        return [
            # name, weight, severe, predicate(df) -> boolean Series
            #
            # `severe` marks the handful of rules that, ON THEIR OWN, are
            # near-certain fraud signals (verified against this dataset:
            # each of the three below fires on ZERO legitimate
            # transactions and 100% of injected fraud) - only THOSE can
            # trigger hard_block (prevention) by themselves. Everything
            # else is a medium-confidence signal that contributes to
            # rule_score (and so to the blended ensemble probability) but
            # must NOT be able to add up with other medium-confidence
            # rules into an automatic block - that combination (mainly
            # legacy_amount_cutoff + extreme_amount_vs_self, two rules
            # that are individually unremarkable on their own) was
            # responsible for most of this engine's false positives
            # before this was gated on severity instead of cumulative
            # score.
            ("legacy_amount_cutoff", 0.3, False,
                lambda df: df["amount"] > self.legacy_amount_cutoff),
            ("balance_mismatch", 0.9, True,
                lambda df: (sender_tracked(df) & (df["sender_balance_error"].abs() > self.balance_error_cutoff))
                | (receiver_tracked(df) & (df["receiver_balance_error"].abs() > self.balance_error_cutoff))),
            ("insufficient_funds_executed", 0.9, True,
                lambda df: sender_tracked(df) & (df["sender_insufficient_funds_flag"] == 1)),
            ("account_drained", 0.7, True,
                lambda df: (df["sender_emptied_account"] == 1) & (df["amount"] > self.large_amount_cutoff)),
            ("extreme_amount_vs_self", 0.5, False,
                lambda df: df["amount_zscore_vs_self"] > config.RULE_ZSCORE_THRESHOLD),
            ("velocity_burst", 0.4, False,
                lambda df: df["user_txn_count_last_1"] >= self.velocity_1h_cutoff),
            ("new_counterparty_large_night_cashout", 0.4, False,
                lambda df: (df["is_new_counterparty"] == 1) & (df["is_night_txn"] == 1)
                & (df["is_cash_out_or_transfer"] == 1) & (df["amount"] > self.large_amount_cutoff)),
            ("mule_fanin_pattern", 0.4, False,
                lambda df: (df["receiver_incoming_count_so_far"] >= self.fanin_min_incoming)
                & (df["receiver_fanin_ratio"] > self.fanin_ratio_cutoff)),
            # SIM-swap / device-cloning: a large cash-out/transfer from a
            # sender whose device changed within the last 24h (including
            # the very transaction the change happened on, where
            # sender_hours_since_device_change == 0) - the classic
            # swap-then-drain playbook, and near-certain fraud on its own:
            # a legitimate device change (new phone) essentially never
            # coincides with an immediate large cash-out in this dataset,
            # since ordinary device changes aren't simulated at all - only
            # feeder.py's injected sim_swap_drain fraud pattern produces
            # this combination. Marked severe on that basis, same as the
            # other three severe rules above.
            ("device_change_then_large_txn", 0.6, True,
                lambda df: (df["sender_hours_since_device_change"] <= 24)
                & (df["amount"] > self.large_amount_cutoff)
                & (df["is_cash_out_or_transfer"] == 1)),
            # Structuring / smurfing: several individually sub-threshold
            # transactions from the same sender within the last hour that
            # ADD UP to a large total - the classic technique for evading a
            # single-transaction amount cutoff. Deliberately not severe:
            # unlike the device-swap combination above, a burst of
            # legitimate small payments (e.g. paying several bills in a
            # row) can plausibly produce this same shape, so it should
            # weigh into the blended probability rather than force a block
            # on its own.
            ("structuring_pattern", 0.4, False,
                lambda df: (df["user_amount_sum_last_6"] > self.structuring_sum_cutoff)
                & (df["amount"] <= self.legacy_amount_cutoff)
                & (df["user_txn_count_last_6"] >= config.RULE_STRUCTURING_MIN_COUNT)),
            # Dormant account reactivation: an account that has gone quiet
            # for RULE_DORMANCY_HOURS (14 days) suddenly moves a large
            # amount - a common account-takeover pattern (attacker gains
            # access to a rarely-used account and empties it before the
            # owner notices). Requires user_txn_count_so_far > 0 so a
            # brand-new account's first-ever transaction (which also reads
            # as a large "time since last txn" via the default sentinel -
            # see online_features.py) is never mistaken for dormancy.
            ("dormant_account_reactivated", 0.5, False,
                lambda df: (df["user_txn_count_so_far"] > 0)
                & (df["time_since_last_txn"] >= config.RULE_DORMANCY_HOURS)
                & (df["amount"] > self.large_amount_cutoff)),
            # Rapid fan-out: transacting to a brand-new counterparty WHILE
            # already in a velocity burst - the mirror image of
            # mule_fanin_pattern (many senders into one receiver): here one
            # sender sprays funds out to many different new receivers in a
            # short window, e.g. distributing stolen funds across several
            # mule accounts before any one of them is flagged.
            ("rapid_fanout_new_counterparty", 0.4, False,
                lambda df: (df["is_new_counterparty"] == 1)
                & (df["user_txn_count_last_6"] >= self.velocity_6h_cutoff)),
        ]

    def evaluate(self, df: pd.DataFrame):
        """Returns (rule_score, hard_block, reasons) all aligned to df's
        index: rule_score is the sum of triggered rules' weights, capped
        at 1.0 - one signal among several the ensemble blends together
        (see ml/ensemble.py). hard_block is True only when at least one
        `severe` rule fired on its own - see the comment in
        _rule_definitions for why this is deliberately NOT "rule_score
        crosses a threshold": that let weak signals gang up into
        false blocks. reasons is a human-readable, comma-separated list
        of which rules fired per row, for the alert queue / audit trail."""
        if self.legacy_amount_cutoff is None:
            raise RuntimeError("RuleEngine.fit() must be called before evaluate()")

        n = len(df)
        score = np.zeros(n)
        severe_triggered = np.zeros(n, dtype=bool)
        fired = [[] for _ in range(n)]
        for name, weight, severe, predicate in self._rule_definitions():
            triggered = predicate(df).fillna(False).to_numpy(dtype=bool)
            score += triggered * weight
            if severe:
                severe_triggered |= triggered
            for i in np.nonzero(triggered)[0]:
                fired[i].append(name)

        score = np.clip(score, 0.0, 1.0)
        reasons = pd.Series([", ".join(r) for r in fired], index=df.index)
        return (
            pd.Series(score, index=df.index),
            pd.Series(severe_triggered, index=df.index),
            reasons,
        )

    # --- baselines.py-compatible interface (comparison report only) --------
    def predict_proba_fraud(self, X):
        score, _, _ = self.evaluate(X)
        return score.to_numpy()

    def predict_flag(self, X):
        score, hard_block, _ = self.evaluate(X)
        return ((score >= config.ALERT_THRESHOLD) | hard_block).astype(int).to_numpy()
