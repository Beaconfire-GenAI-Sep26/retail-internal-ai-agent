from fastapi import APIRouter, Depends

from domain.app.catalog import CATALOG
from domain.app.schemas import ActionCatalogEntry
from domain.app.security import CurrentUser, current_user

router = APIRouter(tags=["catalog"])


@router.get("/catalog/actions", response_model=list[ActionCatalogEntry])
def list_actions(user: CurrentUser = Depends(current_user)):
    """The only actions a proposal may recommend."""
    return CATALOG
