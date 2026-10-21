"""Product/category persistence operations."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.mcp.normalizer import NormalizedCategory, NormalizedProduct
from app.models import Category, Product


class ProductService:
    @staticmethod
    def upsert_category(
        session: Session,
        category: NormalizedCategory,
        observed_at: datetime,
    ) -> Category:
        existing = session.scalar(
            select(Category).where(Category.external_id == category.external_id)
        )
        parent_id = None
        if category.parent_external_id:
            parent = session.scalar(
                select(Category).where(Category.external_id == category.parent_external_id)
            )
            parent_id = parent.id if parent else None
        if existing:
            existing.title = category.title
            existing.url = category.url or existing.url
            existing.parent_id = parent_id or existing.parent_id
            existing.last_seen_at = observed_at
            return existing
        model = Category(
            external_id=category.external_id,
            title=category.title,
            url=category.url,
            parent_id=parent_id,
            last_seen_at=observed_at,
        )
        session.add(model)
        session.flush()
        return model

    @staticmethod
    def upsert_product(
        session: Session,
        product: NormalizedProduct,
        observed_at: datetime,
        category_id: int | None = None,
    ) -> Product:
        existing = session.scalar(select(Product).where(Product.external_id == product.external_id))
        if existing:
            existing.title = product.title
            existing.url = product.url or existing.url
            existing.image_url = product.image_url or existing.image_url
            existing.last_seen_at = observed_at
            # The first verified category is retained as the product's primary
            # category. Separate rank observations preserve every other scope.
            if existing.category_id is None and category_id is not None:
                existing.category_id = category_id
            return existing
        model = Product(
            external_id=product.external_id,
            identity_source=product.identity_source,
            title=product.title,
            url=product.url,
            image_url=product.image_url,
            category_id=category_id,
            first_seen_at=observed_at,
            last_seen_at=observed_at,
        )
        session.add(model)
        session.flush()
        return model
