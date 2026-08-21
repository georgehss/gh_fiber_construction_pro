import sys
import time
from pathlib import Path

# Importando os módulos internos do seu projeto
from config_validator import ConfigValidator
import contagem_hp
import posicionamento
import logger_config

# Descobrindo a raiz do projeto e o caminho do config.json
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config.json"

def exibir_menu():
    print("\n" + "="*50)
    print("      GH Fiber Construction Pro - Terminal")
    print("="*50)
    print("O que desejas fazer?\n")
    print("  [1] - Validar Arquivo de Configuração (config.json)")
    print("  [2] - Executar Contagem de Home Passed (HP)")
    print("  [3] - Executar Posicionamento de Elementos")
    print("  [4] - Rodar Fluxo Completo (Contagem + Posicionamento)")
    print("  [0] - Sair do Sistema")
    print("="*50)

def main():
    print("Iniciando o ambiente virtual e carregando módulos...")
    time.sleep(1)

    while True:
        exibir_menu()
        opcao = input("\nDigite o número da opção desejada: ").strip()

        if opcao == '1':
            print("\n[>>] Lendo config.json e validando parâmetros...")
            try:
                # Agora chamamos a Classe e passamos o caminho do arquivo!
                ConfigValidator.validar(CONFIG_FILE) 
                print("[OK] Configurações validadas com sucesso!")
            except Exception as e:
                print(f"[ERRO] Falha na validação: {e}")

        elif opcao == '2':
            print("\n[>>] Processando arquivos em data/input/ para Contagem de HP...")
            contagem_hp.executar()
            print("[OK] Contagem de HP finalizada. Resultados salvos em data/output/.")

        elif opcao == '3':
            print("\n[>>] Iniciando algoritmo de posicionamento de rede...")
            posicionamento.executar()
            print("[OK] Posicionamento concluído.")

        elif opcao == '4':
            print("\n[>>] Iniciando automação completa do Projeto FTTH...")
            try:
                # No fluxo completo, também precisamos validar corretamente
                ConfigValidator.validar(CONFIG_FILE)
                contagem_hp.executar()
                posicionamento.executar()
                print("[OK] Fluxo completo executado com sucesso!")
            except Exception as e:
                print(f"[ERRO] Falha na execução do fluxo: {e}")

        elif opcao == '0':
            print("\nEncerrando o processo. Até breve!\n")
            sys.exit(0)

        else:
            print("\n[!] Opção inválida. Por favor, escolha um número de 0 a 4.")

if __name__ == "__main__":
    main()