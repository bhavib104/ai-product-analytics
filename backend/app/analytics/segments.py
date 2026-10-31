"""Segment and cluster read models.

Segments are deterministic rules over user-level metrics.  KMeans clusters are
trained in the offline pipeline with a fixed random seed; the API only reads the
stored assignments and never fits a model on request.
"""

from __future__ import annotations

from app.db.duck import query_rows


def segment_summary() -> dict:
    rule_rows = query_rows(
        """
        SELECT segment AS name,
               COUNT(*) AS users,
               ROUND(AVG(sessions_30d), 2) AS avg_sessions_30d,
               ROUND(AVG(events_30d), 2) AS avg_events_30d,
               ROUND(AVG(feature_breadth_30d), 2) AS avg_feature_breadth,
               ROUND(AVG(recency_days), 2) AS avg_recency_days,
               ROUND(AVG(mrr), 2) AS avg_mrr,
               ROUND(SUM(mrr), 2) AS total_mrr,
               ROUND(AVG(lifetime_revenue), 2) AS avg_lifetime_revenue,
               SUM(CASE WHEN lifetime_revenue > 0 THEN 1 ELSE 0 END) AS paying_users
        FROM analytics.user_segments
        GROUP BY 1
        ORDER BY users DESC
        """
    )
    cluster_rows = query_rows(
        """
        SELECT COALESCE(cluster_label, 'Not clustered') AS name,
               COUNT(*) AS users,
               ROUND(AVG(sessions_30d), 2) AS avg_sessions_30d,
               ROUND(AVG(events_30d), 2) AS avg_events_30d,
               ROUND(AVG(feature_breadth_30d), 2) AS avg_feature_breadth,
               ROUND(AVG(recency_days), 2) AS avg_recency_days,
               ROUND(AVG(mrr), 2) AS avg_mrr,
               ROUND(SUM(mrr), 2) AS total_mrr,
               ROUND(AVG(lifetime_revenue), 2) AS avg_lifetime_revenue,
               SUM(CASE WHEN lifetime_revenue > 0 THEN 1 ELSE 0 END) AS paying_users
        FROM analytics.user_segments
        GROUP BY 1
        ORDER BY users DESC
        """
    )
    total = sum(int(row["users"]) for row in rule_rows) or 1
    for row in rule_rows:
        row["share"] = round(int(row["users"]) / total, 6)
    for row in cluster_rows:
        row["share"] = round(int(row["users"]) / total, 6)
    return {
        "rule_segments": rule_rows,
        "clusters": cluster_rows,
        "methodology": {
            "rules": (
                "Deterministic rules over 30-day sessions, events, feature breadth, "
                "recency, tenure and revenue. Rules are evaluated in priority order."
            ),
            "clusters": (
                "KMeans (k=4, fixed seed=42) on scaled log-transformed engagement and "
                "revenue features. Cluster labels are descriptive, not causal."
            ),
        },
    }


def segment_users(segment: str, limit: int = 50, offset: int = 0) -> dict:
    total = query_rows(
        "SELECT COUNT(*) AS n FROM analytics.user_segments WHERE segment = ?", [segment]
    )[0]["n"]
    rows = query_rows(
        """
        SELECT s.user_id, s.segment, s.cluster_label, s.recency_days, s.sessions_30d,
               s.events_30d, s.feature_breadth_30d, s.mrr, s.lifetime_revenue,
               u.country, u.device_type, u.acquisition_channel, u.subscription_type
        FROM analytics.user_segments s
        JOIN analytics.users u ON s.user_id = u.user_id
        WHERE s.segment = ?
        ORDER BY s.lifetime_revenue DESC, s.sessions_30d DESC
        LIMIT ? OFFSET ?
        """,
        [segment, limit, offset],
    )
    return {"segment": segment, "total": int(total), "limit": limit, "offset": offset, "rows": rows}


def segment_metric_comparison(metric: str = "retention_d7") -> dict:
    """Compare a metric across rule-based segments.

    Retention is computed from the dimension mart; other metrics are averaged
    from the stored user-level aggregates.
    """
    if metric in {"retention_d7", "retention_d1", "retention_d14", "retention_d30"}:
        period = int(metric.replace("retention_d", ""))
        rows = query_rows(
            """
            SELECT dimension_value AS segment,
                   SUM(cohort_size) AS cohort_users,
                   SUM(retained_users) AS retained_users,
                   ROUND(SUM(retained_users) * 1.0 / NULLIF(SUM(cohort_size), 0), 6) AS value
            FROM analytics.retention_by_dimension
            WHERE dimension_type = 'segment' AND period_days = ?
            GROUP BY 1 ORDER BY value DESC
            """,
            [period],
        )
        return {"metric": metric, "rows": rows, "unit": "ratio"}
    columns = {
        "mrr": "AVG(mrr)",
        "sessions_30d": "AVG(sessions_30d)",
        "events_30d": "AVG(events_30d)",
        "feature_breadth_30d": "AVG(feature_breadth_30d)",
        "recency_days": "AVG(recency_days)",
        "lifetime_revenue": "AVG(lifetime_revenue)",
    }
    if metric not in columns:
        raise ValueError(f"Unsupported segment metric: {metric}")
    rows = query_rows(
        f"SELECT segment, COUNT(*) AS users, ROUND({columns[metric]}, 6) AS value "
        "FROM analytics.user_segments GROUP BY 1 ORDER BY value DESC"
    )
    return {"metric": metric, "rows": rows, "unit": "average"}
