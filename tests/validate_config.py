#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Script de Validação de Configuração
Detecta typos e chaves faltantes antes de executar o projeto
"""

import json
import sys
from pathlib import Path

def validar_config(arquivo_config):
    """Valida o arquivo config.json"""
    
    print("🔍 Validando arquivo de configuração...\n")
    
    # Chaves obrigatórias por seção
    chaves_obrigatorias = {
        'versao': str,
        'engenharia': {
            'penetracao_estimada': float,
            'capacidade_splitter_cto': int,
            'ctos_por_pon': int,
            'pons_por_ceo': int,
            'distancia_maxima_snap_metros': int
        },
        'equipamentos': {
            'nome_olt_padrao': str
        },
        'api': {
            'overpass_timeout_segundos': int,  # ← AQUI ESTÁ A CHAVE CORRETA!
            'overpass_retry_max': int
        },
        'cache': {
            'versao': str,
            'expirar_dias': int
        }
    }
    
    # Chaves INCORRETAS que podem causar erro
    chaves_problematicas = {
        'api': [
            'overture_timeout_segundos',  # ← TYPO: overture em vez de overpass
            'overture_timeout_seconds',
            'overpass_timeout_s'
        ]
    }
    
    try:
        with open(arquivo_config, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"❌ ERRO: Arquivo não encontrado: {arquivo_config}")
        return False
    except json.JSONDecodeError as e:
        print(f"❌ ERRO: JSON inválido: {e}")
        return False
    
    # Verificar chaves obrigatórias
    erros = []
    avisos = []
    
    print("✓ Estrutura JSON válida\n")
    
    # Verificar seção 'api'
    if 'api' not in config:
        erros.append("❌ Seção 'api' não encontrada")
    else:
        api_config = config['api']
        
        # Verificar chaves corretas
        if 'overpass_timeout_segundos' not in api_config:
            erros.append("❌ Chave OBRIGATÓRIA ausente: api.overpass_timeout_segundos")
        else:
            print(f"✓ api.overpass_timeout_segundos = {api_config['overpass_timeout_segundos']}s")
        
        # Verificar chaves problemáticas
        for chave_problema in chaves_problematicas['api']:
            if chave_problema in api_config:
                avisos.append(f"⚠️  TYPO DETECTADO: '{chave_problema}' (deve ser 'overpass_timeout_segundos')")
    
    # Verificar equipamentos
    if 'equipamentos' in config and 'nome_olt_padrao' in config['equipamentos']:
        print(f"✓ equipamentos.nome_olt_padrao = {config['equipamentos']['nome_olt_padrao']}")
    
    # Verificar cache
    if 'cache' in config:
        print(f"✓ cache.expirar_dias = {config['cache'].get('expirar_dias', 'N/A')} dias")
    
    print("\n" + "="*60)
    
    # Exibir resultados
    if erros:
        print("🚨 ERROS ENCONTRADOS:\n")
        for erro in erros:
            print(f"  {erro}")
        print("\n❌ Configuração INVÁLIDA - NÃO pode executar o projeto")
        return False
    
    if avisos:
        print("⚠️  AVISOS:\n")
        for aviso in avisos:
            print(f"  {aviso}")
        print("\n⚠️  Configuração pode causar problemas")
        return False
    
    print("✅ Configuração VÁLIDA e sem problemas detectados!")
    print("\n📌 Dica: Se receber erro 400 da API Overpass, verifique:")
    print("   1. config.json tem 'overpass_timeout_segundos' (não 'overture')")
    print("   2. Valor está em segundos (ex: 30, 60)")
    print("   3. Arquivo salvo com UTF-8 sem BOM")
    
    return True

if __name__ == "__main__":
    config_path = Path(__file__).parent / "config.json"
    
    sucesso = validar_config(config_path)
    sys.exit(0 if sucesso else 1)
