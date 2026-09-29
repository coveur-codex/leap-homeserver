import asyncio
from io import BytesIO
from pathlib import Path
import httpx
from PIL import Image, ImageOps
from app.core.config import settings
from app.core.security import validate_external_url

def resize_image(data: bytes, size: tuple[int,int], mode: str) -> Image.Image:
    image=Image.open(BytesIO(data)).convert("RGB")
    if mode=="fit": return ImageOps.pad(image,size,color=(20,25,32),method=Image.Resampling.LANCZOS)
    return ImageOps.fit(image,size,method=Image.Resampling.LANCZOS)
def process_image(data: bytes, article_id: int, mode: str="center_crop") -> tuple[str,str]:
    folder=settings.data_dir/"images"/"news"/str(article_id); folder.mkdir(parents=True,exist_ok=True)
    original=folder/"original.jpg"; Image.open(BytesIO(data)).convert("RGB").save(original,"JPEG",quality=88)
    resize_image(data,(120,80),mode).save(folder/"thumb.jpg","JPEG",quality=82,optimize=True)
    resize_image(data,(142,100),mode).save(folder/"hero.jpg","JPEG",quality=82,optimize=True)
    return str(original),str(folder/"hero.jpg")
def download_and_process(url: str, article_id: int, mode: str) -> tuple[str,str]:
    validate_external_url(url)
    with httpx.Client(timeout=settings.request_timeout,follow_redirects=False) as client:
        response=client.get(url); response.raise_for_status()
        if len(response.content)>settings.max_download_bytes: raise ValueError("Bild ist zu groß")
        return process_image(response.content,article_id,mode)

async def download_and_process_async(url: str, article_id: int, mode: str, client: httpx.AsyncClient) -> tuple[str,str]:
    """Download an article image without blocking the server's event loop."""
    validate_external_url(url)
    response=await client.get(url)
    response.raise_for_status()
    if len(response.content)>settings.max_download_bytes: raise ValueError("Bild ist zu groß")
    return await asyncio.to_thread(process_image,response.content,article_id,mode)
