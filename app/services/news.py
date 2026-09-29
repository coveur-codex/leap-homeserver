from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Article, Device, Feed


def articles_for_device(
    device: Device,
    db: Session,
    *,
    limit: int | None = None,
    since: datetime | None = None,
) -> list[Article]:
    """Return the same personalized, recent article list on every surface."""
    wanted_categories = {category.slug for category in device.categories}
    included_feeds = set(device.included_feed_ids)
    excluded_feeds = set(device.excluded_feed_ids)
    cutoff = max(
        since or datetime.min.replace(tzinfo=timezone.utc),
        datetime.now(timezone.utc) - timedelta(hours=device.news_max_age_hours),
    )
    query = (
        select(Article)
        .join(Feed)
        .where(Article.published_at >= cutoff, ~Article.feed_id.in_(excluded_feeds))
        .order_by(Article.published_at.desc())
    )
    articles = [
        article
        for article in db.scalars(query).all()
        if article.category in wanted_categories or article.feed_id in included_feeds
    ]
    return articles[: (limit if limit is not None else device.news_limit)]
