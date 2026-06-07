"""Cross-item annotations feed: every highlight + comment in one timeline."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from app.db import get_session
from app.models import Comment, Highlight, Item
from app.schemas import AnnotationRead, ItemBrief

router = APIRouter(prefix="/api/annotations", tags=["annotations"])


def _brief(item: Item) -> ItemBrief:
    return ItemBrief(
        id=item.id,
        title=item.title,
        platform=item.platform,
        source_url=item.source_url,
        author=item.author,
        thumbnail=item.thumbnail,
    )


@router.get("", response_model=list[AnnotationRead])
def list_annotations(
    session: Session = Depends(get_session),
    kind: str | None = Query(default=None, description="highlight | comment"),
    item_id: int | None = None,
    limit: int = Query(default=200, le=1000),
    offset: int = 0,
) -> list[AnnotationRead]:
    """Merged, newest-first feed of all highlights and comments across items.

    Items are loaded in one batch so each annotation carries enough context
    (title, platform, link) to render and deep-link without an extra fetch.
    """
    rows: list[AnnotationRead] = []
    briefs: dict[int, ItemBrief] = {}

    def brief_for(iid: int) -> ItemBrief | None:
        if iid not in briefs:
            item = session.get(Item, iid)
            if item is None:
                briefs[iid] = None  # type: ignore[assignment]
            else:
                briefs[iid] = _brief(item)
        return briefs[iid]

    if kind in (None, "highlight"):
        stmt = select(Highlight)
        if item_id is not None:
            stmt = stmt.where(Highlight.item_id == item_id)
        for h in session.exec(stmt).all():
            b = brief_for(h.item_id)
            if b is None:
                continue
            rows.append(
                AnnotationRead(
                    kind="highlight",
                    id=h.id,
                    item=b,
                    created_at=h.created_at,
                    quote=h.quote,
                    source=h.source,
                    color=h.color,
                    body=h.note,
                )
            )

    if kind in (None, "comment"):
        stmt = select(Comment)
        if item_id is not None:
            stmt = stmt.where(Comment.item_id == item_id)
        for c in session.exec(stmt).all():
            b = brief_for(c.item_id)
            if b is None:
                continue
            rows.append(
                AnnotationRead(
                    kind="comment",
                    id=c.id,
                    item=b,
                    created_at=c.created_at,
                    body=c.body,
                )
            )

    rows.sort(key=lambda r: r.created_at, reverse=True)
    return rows[offset : offset + limit]
