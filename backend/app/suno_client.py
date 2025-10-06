"""
Cliente para o novo Suno-API (SunoAI-API/Suno-API) - CORRIGIDO
"""
import asyncio
import os
import aiohttp
import logging
from pathlib import Path
from typing import Dict, Tuple, Optional, Union, List

logger = logging.getLogger(__name__)

SUNO_API_BASE = os.environ.get("SUNO_API_URL", "http://suno-api:3000")
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "./generated_audio"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DOWNLOAD_TIMEOUT = 600  # 10 minutos


async def wait_for_generation(
    session: aiohttp.ClientSession,
    audio_id: str,
    max_wait: float = 480.0,
    poll_interval: float = 5.0
) -> Optional[Dict]:
    """
    Aguarda até que a geração seja concluída.
    """
    elapsed = 0.0
    while elapsed < max_wait:
        try:
            async with session.get(f"{SUNO_API_BASE}/feed/{audio_id}") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    logger.info(f"Resposta da API (tipo: {type(data)}): {str(data)[:200]}")
                    
                    # Normaliza a resposta
                    if isinstance(data, list) and len(data) > 0:
                        audio_info = data[0]
                    elif isinstance(data, dict):
                        audio_info = data
                    else:
                        logger.warning(f"Formato inesperado (tipo {type(data)}): {data}")
                        await asyncio.sleep(poll_interval)
                        elapsed += poll_interval
                        continue
                    
                    # Verifica se audio_info é realmente um dict
                    if not isinstance(audio_info, dict):
                        logger.error(f"audio_info não é dict, é {type(audio_info)}: {audio_info}")
                        await asyncio.sleep(poll_interval)
                        elapsed += poll_interval
                        continue
                    
                    status = audio_info.get("status")
                    
                    logger.info(f"Status da geração {audio_id}: {status}")
                    
                    if status == "complete":
                        return audio_info
                    elif status == "error":
                        error_msg = audio_info.get("error_message", "Erro desconhecido")
                        raise Exception(f"Erro na geração Suno: {error_msg}")
                else:
                    logger.warning(f"Status HTTP {resp.status} ao verificar geração")
                    
        except Exception as e:
            logger.warning(f"Erro ao verificar status: {e}")
        
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
    
    raise TimeoutError(f"Timeout aguardando geração do áudio {audio_id}")


async def download_audio(
    session: aiohttp.ClientSession,
    url: str,
    output_path: str
) -> None:
    """Baixa o arquivo de áudio da URL fornecida."""
    timeout = aiohttp.ClientTimeout(total=DOWNLOAD_TIMEOUT)
    async with session.get(url, timeout=timeout) as resp:
        if resp.status != 200:
            raise Exception(f"Falha ao baixar áudio: HTTP {resp.status}")
        
        with open(output_path, 'wb') as f:
            async for chunk in resp.content.iter_chunked(8192):
                f.write(chunk)
    
    logger.info(f"Áudio baixado: {output_path}")


async def custom_generate(
    title: str,
    style: str,
    prompt: str,
    model: str = "chirp-v3-5",
    duration_target: float = 240.0,
    prefer_wav: bool = True,
    allow_mp3_to_wav: bool = True,
    make_instrumental: bool = False,
    wait_audio: bool = True
) -> Tuple[str, Dict[str, str], bool]:
    """
    Gera uma música usando o novo Suno-API.
    """
    async with aiohttp.ClientSession() as session:
        # Mapeia modelo
        if model == "v5":
            mv = "chirp-v3-5"
        elif model == "v4.5":
            mv = "chirp-v3-0"
        else:
            mv = model
        
        # Prepara payload
        payload = {
            "prompt": prompt,
            "tags": style,
            "title": title,
            "mv": mv,
            "negative_tags": ""
        }
        
        logger.info(f"Gerando música: {title} | Estilo: {style}")
        logger.debug(f"Payload: {payload}")
        
        # Envia requisição
        async with session.post(
            f"{SUNO_API_BASE}/generate",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise Exception(f"Erro na API Suno: {resp.status} - {error_text}")
            
            result = await resp.json()
            
            # Log detalhado da resposta
            logger.info(f"Resposta da API /generate (tipo: {type(result)}): {str(result)[:500]}")
            
            # A API pode retornar diferentes formatos
            if isinstance(result, str):
                # Verifica se é uma mensagem de erro
                if "error" in result.lower() or "503" in result:
                    raise Exception(f"Erro retornado pela API Suno: {result}")
                # Se retornou uma string, pode ser apenas o ID
                audio_id = result
                logger.info(f"API retornou string (ID): {audio_id}")
            elif isinstance(result, list):
                if len(result) == 0:
                    raise Exception("API Suno retornou lista vazia")
                
                # Pega o primeiro item
                first_item = result[0]
                
                if isinstance(first_item, str):
                    audio_id = first_item
                elif isinstance(first_item, dict):
                    audio_id = first_item.get("id")
                    if not audio_id:
                        raise Exception(f"Objeto sem 'id': {first_item}")
                else:
                    raise Exception(f"Formato inesperado no array: {type(first_item)}")
                    
            elif isinstance(result, dict):
                audio_id = result.get("id")
                if not audio_id:
                    raise Exception(f"Resposta dict sem 'id': {result}")
            else:
                raise Exception(f"Formato de resposta não suportado: {type(result)}")
            
            if not audio_id:
                raise Exception(f"ID de geração não encontrado na resposta: {result}")
            
            logger.info(f"Geração iniciada com ID: {audio_id}")
            
            # Aguarda conclusão
            audio_info = await wait_for_generation(session, audio_id)
            
            if not isinstance(audio_info, dict):
                raise Exception(f"wait_for_generation retornou tipo inválido: {type(audio_info)}")
            
            # Extrai URL do áudio
            audio_url = audio_info.get("audio_url")
            video_url = audio_info.get("video_url")
            
            if not audio_url:
                raise Exception(f"URL de áudio não encontrada em: {audio_info}")
            
            # Determina formato
            is_wav = audio_url.lower().endswith('.wav')
            extension = 'wav' if is_wav else 'mp3'
            
            # Define caminho de saída
            output_filename = f"{audio_id}.{extension}"
            output_path = OUTPUT_DIR / output_filename
            
            # Baixa o áudio
            logger.info(f"Baixando áudio de: {audio_url}")
            await download_audio(session, audio_url, str(output_path))
            
            # TODO: Converter MP3->WAV se necessário
            if not is_wav and prefer_wav and allow_mp3_to_wav:
                logger.warning("Conversão MP3->WAV não implementada. Usando MP3.")
            
            urls = {
                "audio_url": str(output_path),
                "video_url": video_url or "",
                "original_audio_url": audio_url
            }
            
            return audio_id, urls, is_wav


async def extend_audio(
    original_id: str,
    extend_seconds: float = 60.0,
    prefer_wav: bool = True,
    continue_at: Optional[float] = None
) -> Tuple[str, Dict[str, str], bool]:
    """
    Estende um áudio existente.
    """
    async with aiohttp.ClientSession() as session:
        payload = {
            "continue_clip_id": original_id,
            "continue_at": int(continue_at) if continue_at else None,
            "prompt": "",
            "tags": "",
            "title": "",
            "mv": "chirp-v3-5",
            "negative_tags": ""
        }
        
        logger.info(f"Estendendo áudio: {original_id}")
        
        async with session.post(
            f"{SUNO_API_BASE}/generate",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise Exception(f"Erro ao estender áudio: {resp.status} - {error_text}")
            
            result = await resp.json()
            
            logger.info(f"Resposta extend (tipo: {type(result)}): {str(result)[:500]}")
            
            # Extrai ID da resposta
            if isinstance(result, str):
                audio_id = result
            elif isinstance(result, list) and len(result) > 0:
                first = result[0]
                audio_id = first if isinstance(first, str) else first.get("id")
            elif isinstance(result, dict):
                audio_id = result.get("id")
            else:
                raise Exception(f"Formato de resposta extend não suportado: {type(result)}")
            
            if not audio_id:
                raise Exception("ID não encontrado na resposta de extend")
            
            # Aguarda conclusão
            audio_info = await wait_for_generation(session, audio_id)
            
            audio_url = audio_info.get("audio_url")
            if not audio_url:
                raise Exception(f"URL de áudio estendido não encontrada em: {audio_info}")
            
            is_wav = audio_url.lower().endswith('.wav')
            extension = 'wav' if is_wav else 'mp3'
            
            output_filename = f"{audio_id}_ext.{extension}"
            output_path = OUTPUT_DIR / output_filename
            
            await download_audio(session, audio_url, str(output_path))
            
            urls = {
                "audio_url": str(output_path),
                "original_audio_url": audio_url
            }
            
            return audio_id, urls, is_wav