from fastapi import APIRouter

router = APIRouter()

@router.get("/items")
async def get_items():
    return [{"id": 1, "name": "Item1"}, {"id": 2, "name": "Item2"}]
