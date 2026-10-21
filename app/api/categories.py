from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import as_utc, get_db
from app.models import Category
from app.schemas.api import CategoryResponse

router = APIRouter(prefix="/api", tags=["categories"])


@router.get("/categories", response_model=list[CategoryResponse])
def categories(session: Session = Depends(get_db)) -> list[dict]:
    records = list(session.scalars(select(Category).order_by(Category.title, Category.id)))
    nodes = {
        category.id: {
            "id": category.id,
            "external_id": category.external_id,
            "title": category.title,
            "parent_id": category.parent_id,
            "url": category.url,
            "last_seen_at": as_utc(category.last_seen_at),
            "children": [],
        }
        for category in records
    }
    roots: list[dict] = []
    for category in records:
        node = nodes[category.id]
        if category.parent_id in nodes:
            nodes[category.parent_id]["children"].append(node)
        else:
            roots.append(node)
    return roots
