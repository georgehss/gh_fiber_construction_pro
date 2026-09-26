"""Ponto de entrada principal - GH Fiber Construction Pro.

Terminal interativo com despacho de rotinas e manual integrado do sistema.
"""

import os
import sys
import time
from pathlib import Path

# Importando os módulos internos do projeto
from .config import carregar_config
from . import contagem_hp
from . import posicionamento


def limpar_tela():
    """Limpa o console de acordo com o sistema operacional."""
    os.system("cls" if os.name == "nt" else "clear")


def pausar():
    """Pausa a execução para permitir leitura antes de redesenhar o menu."""
    input("\n[Pressione Enter para continuar...]")


def exibir_secao(titulo: str):
    print("\n" + "=" * 65)
    print(f"  📖 MANUAL: {titulo.upper()}")
    print("=" * 65)


def manual_visao_geral():
    exibir_secao("1. Visão Geral e Propósito")
    print("""
O GH Fiber Construction Pro é uma plataforma desenvolvida para automatizar
o pré-planejamento executivo de redes de fibra óptica FTTH (Fiber to the Home).

Objetivos Centrais:
  • Localizar e quantificar edificações reais (HPs) a partir de polígonos.
  • Dimensionar caixas de terminação (CTOs), portas PON e caixas de emenda (CEOs).
  • Traçar o roteamento físico dos cabos pelas vias urbanas ou postes cadastrados.
  • Implementar anéis redundantes de proteção no backbone (alta disponibilidade).
  • Validar o orçamento de potência óptica (Loss Budget) da central até o cliente.
    """)


def manual_menu_rotinas():
    exibir_secao("2. Guia de Opções do Terminal")
    print("""
[1] - Validar Arquivo de Configuração (config.json):
      Lê o arquivo de configuração, valida o formato, a existência de chaves
      obrigatórias e injeta parâmetros padrão caso você esteja utilizando uma
      configuração de versões anteriores (retrocompatibilidade).

[2] - Executar Contagem de Home Passed (HP):
      1. Lê o polígono delimitado do projeto (.kml/.kmz) na pasta 'data/input/'.
      2. Consulta a API pública do Overture Maps (camada building) para baixar
         todas as casas/edificações contidas dentro da área.
      3. Salva os dados em cache local (para evitar downloads repetitivos).
      4. Gera o arquivo de marcação geográfica de residências e faz o primeiro
         cálculo teórico de caixas necessárias.

[3] - Executar Posicionamento de Elementos:
      1. Recupera as casas salvas pelo módulo de Contagem de HP.
      2. Baixa a malha viária do OpenStreetMap (e/ou lê postes físicos).
      3. Agrupa as casas de forma capacitada (máximo rígido de 16 HP por CTO).
      4. Aloca CTOs em PONs (até 8 CTOs/PON) e PONs em CEOs (até 2 PONs/CEO).
      5. Faz o roteamento contínuo dos cabos de distribuição e do backbone (em anel).
      6. Calcula o orçamento óptico (atenuação em dB) da OLT a cada CTO.
      7. Exporta arquivos KML isolados por camada e o JSON com o laudo da rede.

[4] - Rodar Fluxo Completo (Contagem + Posicionamento):
      Executa as etapas [1], [2] e [3] sequencialmente em lote, ideal para
      processar um novo projeto do início ao fim de uma só vez.

[0] - Sair do Sistema:
      Encerra a execução do terminal de forma segura.
    """)


def manual_arquivos_entrada_saida():
    exibir_secao("3. Arquivos de Entrada e Saída")
    print("""
PASTA DE ENTRADA ('data/input/'):
  Coloque aqui os arquivos KML ou KMZ gerados no Google Earth ou QGIS:
  
  • Arquivo do Projeto: Polígono fechado que delimita a área do bairro/cidade.
  • Arquivo de Postes (Opcional): Pontos com os postes reais da concessionária.
    Quando presente, o roteador ancora os cabos na calçada e evita travessias.
  • Arquivo de Correções (Opcional): KML contendo posições manuais de CTO/CEO
    feitas pelo projetista para sobrepor o algoritmo automático.

PASTA DE SAÍDA ('data/output/'):
  Arquivos gerados automaticamente prontos para abrir no Google Earth:
  
  • '<Projeto> - Residências HP.kml': Pontos de cada casa detectada.
  • '<Projeto> - Caixas de Terminação Óptica (CTO).kml': CTOs com ícones por PON.
  • '<Projeto> - Caixas de Emenda Óptica (CEO).kml': CEOs posicionadas.
  • '<Projeto> - OLT.kml': Localização da central (se informada no config).
  • '<Projeto> - Cabos de Distribuição.kml': Rotas dos cabos entre CEO e CTOs.
  • '<Projeto> - Cabos de Backbone (OLT-CEOs).kml': Cabo primário (Anel/Árvore).
  • '<Projeto> - Excecoes de Roteamento.kml': Vias sem conectividade identificadas.
  • '<Projeto> - Alocacao FTTH.json': Relatório completo com métricas de engenharia
    e laudos do Orçamento Óptico (Aprovado/Reprovado).
  • 'logs/': Arquivos de texto com o histórico e rastreamento de cada execução.
    """)


def manual_regras_engenharia():
    exibir_secao("4. Regras de Engenharia e Topologia")
    print("""
1. Dimensionamento da CTO:
   • Cobertura Física: Máximo rígido de 16 HPs por CTO.
   • Splitters: Nasce com 1x8 (atende penetração estimada de 50%, ou 8 clientes).
     A infraestrutura física já prevê expansão para 1x16 (atende todos os 16 HPs).
   • Fórmula de Dimensionamento: CTOs = teto(HP_planejados / 16).

2. Hierarquia Óptica:
   • CTO -> PON: Cada porta PON atende até 8 CTOs (128 HPs potenciais).
   • PON -> CEO: Cada Caixa de Emenda Óptica atende até 2 PONs (16 CTOs).

3. Roteamento e Física de Lançamento (Fase 7):
   • Flecha de Cabo: Multiplicador padrão de +3% na distância para absorver
     o caimento da fibra entre os vãos dos postes.
   • Sobras Técnicas: 10m de cabo em cada CTO, 30m na CEO e 50m na OLT.
   • Custo de Travessia: Rotas que cruzam a rua têm custo triplicado no grafo,
     forçando a permanência na calçada do mesmo lado.

4. Backbone Redundante em Anel (Fase 8):
   • Topologia em Anel (TSP): A rota sai da OLT, interliga todas as CEOs e
     retorna à OLT, garantindo dupla rota física em caso de rompimento de cabo.
   • Fallback Automático: Caso haja ruas sem saída impedindo o fechamento
     do ciclo, o sistema avisa no log e reverte para Árvore Geradora Mínima (MST).

5. Orçamento Óptico / Loss Budget (Fase 9):
   • OLT Classe C+: Potência de transmissão padrão configurada em +4.5 dBm.
   • Sensibilidade da ONU: Limite de recepção em -27.0 dBm com margem de 2.0 dB.
   • Perdas Acumuladas: Fibra (0.25 dB/km) + Fusões (0.1 dB) + Conectores (0.5 dB)
     + Splitters (10.5 dB no 1x8 + 13.5 dB no 1x16).
   • Se a atenuação total ultrapassar o limite, a CTO é classificada como REPROVADA.
    """)


def manual_configuracao():
    exibir_secao("5. Guia de Parâmetros do config.json")
    print("""
Principais campos configuráveis no 'config.json':

"versao": "9.0"
"entrada":
  "arquivo_projeto": null (ou "MeuProjeto.kml") -> Nome do KML em data/input/
  "arquivo_postes": null (ou "MeusPostes.kml") -> Nome do arquivo de postes
  "arquivo_correcoes": null -> Posições manuais de caixas

"engenharia":
  "penetracao_estimada": 0.5 (Taxa de clientes esperados, ex: 50%)
  "reserva_capacidade_percentual": 0.0 (Gera CTOs extras sobre a contagem de HPs)
  "capacidade_hp_por_cto": 16 (Limite máximo por caixa)
  "topologia_backbone": { "modo": "anel" } -> Aceita "anel" ou "arvore"
  "fisica":
    "margem_flecha_percentual": 0.03 (3% de sobra para flecha)
    "reserva_tecnica_cto_metros": 10.0
    "reserva_tecnica_ceo_metros": 30.0

"orcamento_optico":
  "potencia_saida_olt_dbm": 4.5
  "sensibilidade_minima_onu_dbm": -27.0
  "margem_seguranca_db": 2.0

"equipamentos":
  "olt": { "latitude": -2.53, "longitude": -44.28 } -> Ponto físico da central
    """)


def exibir_manual_interativo():
    """Submenu de Ajuda com navegação por capítulos."""
    while True:
        limpar_tela()
        print("=================================================================")
        print("        MANUAL DE INSTRUÇÕES - GH FIBER CONSTRUCTION PRO         ")
        print("=================================================================")
        print("Escolha o tópico que deseja consultar:\n")
        print("  [1] - Visão Geral e Propósito do Projeto")
        print("  [2] - Guia Passo a Passo das Opções do Terminal ([1] a [4])")
        print("  [3] - Estrutura de Arquivos de Entrada e Saída (Pastas data/)")
        print("  [4] - Regras de Engenharia, Topologia em Anel e Perda Óptica")
        print("  [5] - Dicionário de Parâmetros do Arquivo config.json")
        print("  [6] - Visualizar Manual Completo (Todos os tópicos)")
        print("  [0] - Retornar ao Menu Principal")
        print("=================================================================")
        
        escolha = input("\nDigite o número do tópico desejado: ").strip()

        if escolha == "1":
            manual_visao_geral()
            pausar()
        elif escolha == "2":
            manual_menu_rotinas()
            pausar()
        elif escolha == "3":
            manual_arquivos_entrada_saida()
            pausar()
        elif escolha == "4":
            manual_regras_engenharia()
            pausar()
        elif escolha == "5":
            manual_configuracao()
            pausar()
        elif escolha == "6":
            manual_visao_geral()
            manual_menu_rotinas()
            manual_arquivos_entrada_saida()
            manual_regras_engenharia()
            manual_configuracao()
            pausar()
        elif escolha == "0":
            break
        else:
            print("\n❌ Opção inválida. Escolha entre 0 e 6.")
            pausar()


def exibir_menu_principal():
    limpar_tela()
    print("==================================================")
    print("      GH Fiber Construction Pro - Terminal        ")
    print("==================================================")
    print("O que desejas fazer?\n")
    print("  [1] - Validar Arquivo de Configuração (config.json)")
    print("  [2] - Executar Contagem de Home Passed (HP)")
    print("  [3] - Executar Posicionamento de Elementos")
    print("  [4] - Rodar Fluxo Completo (Contagem + Posicionamento)")
    print("  [5] - Manual de Instruções / Ajuda (Guia Completo)")
    print("  [0] - Sair do Sistema")
    print("==================================================")


def main():
    print("Carregando módulos do GH Fiber Construction Pro...")
    time.sleep(0.3)

    while True:
        try:
            exibir_menu_principal()
            opcao = input("\nDigite o número da opção desejada: ").strip()

            if opcao == "1":
                print("\n[>>] Lendo config.json e validando parâmetros...")
                try:
                    config = carregar_config()
                    print("\n[OK] Configurações validadas com sucesso!")
                    print(f"  • Versão do config: {config.get('versao')}")
                    print(f"  • Modo do Backbone: {config.get('engenharia', {}).get('topologia_backbone', {}).get('modo', 'arvore').upper()}")
                    print(f"  • Limite por CTO: {config.get('engenharia', {}).get('capacidade_hp_por_cto')} HP")
                except Exception as e:
                    print(f"\n[ERRO] Falha na validação do config.json: {e}")
                pausar()

            elif opcao == "2":
                print("\n[>>] Processando arquivos em data/input/ para Contagem de HP...")
                try:
                    contagem_hp.executar()
                    print("\n[OK] Contagem de HP finalizada. Resultados salvos em data/output/.")
                except Exception as e:
                    print(f"\n[ERRO] Falha durante a Contagem de HP: {e}")
                pausar()

            elif opcao == "3":
                print("\n[>>] Iniciando algoritmo de posicionamento e roteamento de rede...")
                try:
                    posicionamento.executar()
                    print("\n[OK] Posicionamento e auditoria óptica concluídos.")
                except Exception as e:
                    print(f"\n[ERRO] Falha no Posicionamento de Rede: {e}")
                pausar()

            elif opcao == "4":
                print("\n[>>] Iniciando automação completa do Projeto FTTH...")
                try:
                    print("\n--- Etapa 1: Validação ---")
                    carregar_config()
                    print("Configuração válida.")

                    print("\n--- Etapa 2: Contagem de HP ---")
                    contagem_hp.executar()

                    print("\n--- Etapa 3: Posicionamento e Orçamento Óptico ---")
                    posicionamento.executar()

                    print("\n[OK] Fluxo completo executado com sucesso!")
                except Exception as e:
                    print(f"\n[ERRO] Falha na execução do fluxo completo: {e}")
                pausar()

            elif opcao == "5":
                exibir_manual_interativo()

            elif opcao == "0":
                print("\nEncerrando o GH Fiber Construction Pro. Até logo!\n")
                sys.exit(0)

            else:
                print("\n❌ Opção inválida. Por favor, escolha um número de 0 a 5.")
                pausar()

        except KeyboardInterrupt:
            print("\n\nOperação cancelada pelo usuário. Encerrando o sistema...")
            sys.exit(0)


if __name__ == "__main__":
    main()