"""
Módulo responsável pelo cálculo de Loss Budget (Orçamento Óptico) da rede FTTH.
Garante que a atenuação total da OLT até o cliente final não ultrapasse 
os limites físicos dos transceptores (ex: Classe C+).
"""

from typing import Dict, Any, Tuple

class CalculadoraOrcamentoOptico:
    def __init__(self, config: Dict[str, Any]):
        opt_config = config.get("orcamento_optico", {})
        self.potencia_olt = opt_config.get("potencia_saida_olt_dbm", 4.5)
        self.sensibilidade_onu = opt_config.get("sensibilidade_minima_onu_dbm", -27.0)
        self.margem = opt_config.get("margem_seguranca_db", 2.0)
        
        perdas = opt_config.get("perdas", {})
        self.perda_fibra_km = perdas.get("fibra_por_km", 0.25)
        self.perda_fusao = perdas.get("fusao", 0.1)
        self.perda_conector = perdas.get("conector", 0.5)
        self.perda_sp_inicial = perdas.get("splitter_1x8", 10.5)
        self.perda_sp_expansao = perdas.get("splitter_1x16", 13.5)

        self.limite_atenuacao_permitida = (self.potencia_olt - self.sensibilidade_onu) - self.margem

    def calcular_atenuacao_cto(self, distancia_feeder_m: float, distancia_distribuicao_m: float, qtd_fusoes: int = 1) -> Tuple[float, float, bool]:
        """
        Calcula a atenuação total de uma rota da OLT até o assinante (HP).
        
        Retorna:
            (atenuacao_total_db, sinal_recebido_dbm, aprovado)
        """
        # Conversão de metros para quilômetros
        km_totais = (distancia_feeder_m + distancia_distribuicao_m) / 1000.0
        
        atenuacao_cabo = km_totais * self.perda_fibra_km
        atenuacao_fusoes = qtd_fusoes * self.perda_fusao
        
        # Consideramos 2 conectores padrão (um na OLT e um na ONU do cliente)
        atenuacao_conectores = 2 * self.perda_conector
        
        # O sinal passa pelos dois splitters (CEO e CTO)
        atenuacao_splitters = self.perda_sp_inicial + self.perda_sp_expansao

        atenuacao_total = atenuacao_cabo + atenuacao_fusoes + atenuacao_conectores + atenuacao_splitters
        sinal_recebido = self.potencia_olt - atenuacao_total
        
        aprovado = atenuacao_total <= self.limite_atenuacao_permitida

        return round(atenuacao_total, 2), round(sinal_recebido, 2), aprovado

    def emitir_laudo(self, atenuacao: float, sinal: float, aprovado: bool) -> str:
        if aprovado:
            return f"APROVADO (Sinal Estimado: {sinal} dBm | Atenuação: {atenuacao} dB)"
        return f"REPROVADO (Sinal Estimado: {sinal} dBm - Abaixo da sensibilidade)"