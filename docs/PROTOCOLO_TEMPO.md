# Protocolo para medir o tempo economizado

O README **não** afirma nenhuma economia de tempo porque ela ainda não foi medida. O agente processa um PDF em
~12 ms (medido), mas isso ignora o que importa: o tempo de uma pessoa com e sem o agente. Para medir de verdade:

1. **Amostra:** escolha 20 PDFs (os sintéticos em `data/synthetic/` servem para um primeiro ensaio; para um número
   defensável, use documentos reais de um caso de uso real, com autorização e sem dados pessoais).
2. **Manual (sem agente):** com cronômetro, trate cada PDF como o processo atual: ler, classificar, achar cliente,
   pedido e valor, escrever o resumo e registrar o ticket. Anote os segundos.
3. **Com agente:** faça o agente processar os mesmos PDFs. Para cada um que ficou em `PENDENTE_REVISAO`, cronometre
   quanto leva para abrir no painel, conferir e aprovar ou rejeitar.
4. Preencha `results/tempos_medidos.csv`:
   ```
   tipo,arquivo,segundos
   manual,doc_000_normal.pdf,214
   revisao,doc_000_normal.pdf,38
   ```
5. Rode: `python -m business_agent.benchmark --tempos results/tempos_medidos.csv`
   O script recusa menos de 5 medições de cada tipo e pode devolver economia **negativa**, se a revisão custar caro.

Anote junto: quem mediu, quantos documentos, se eram reais ou sintéticos e o nível de experiência de quem mediu.
