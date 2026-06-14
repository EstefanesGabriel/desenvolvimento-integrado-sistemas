# Desenvolvimento Integrado de Sistemas — Reconstrução Tomográfica

Comparativo de desempenho entre um servidor **compilado (C# / .NET)** e um servidor **interpretado (Python / FastAPI)** na reconstrução de imagens tomográficas via algoritmos iterativos CGNE e CGNR.

---

## Estrutura do Projeto

```
desenvolvimento-integrado-sistemas/
│
├── Controllers/                             # C# – controlador REST
│   └── ProcessamentoUnificadoController.cs
├── Services/                                # C# – lógica de negócio
│   ├── MatrizService.cs                     #   carrega/converte H (CSV → .mtx, com cache)
│   ├── ProcessamentoService.cs              #   algoritmos CGNE e CGNR
│   └── ImageService.cs                      #   normalização e geração de PNG
├── ViewModels/                              # C# – modelos de request/response
│   ├── RequisicaoUnificada.cs
│   ├── DadosReconstrucao.cs
│   └── ResultViewModel.cs
├── Properties/
│   └── launchSettings.json
├── ServerDotNet.csproj
├── Program.cs
├── appsettings.json
├── appsettings.Development.json
│
├── servidor-python/                         # Servidor Python (FastAPI)
│   ├── main.py                              #   ponto de entrada + CORS + health check
│   ├── requirements.txt
│   ├── controllers/
│   │   └── reconstrucao_controller.py       #   endpoint POST /api/v1/reconstruct
│   ├── services/
│   │   ├── matriz_service.py                #   carrega/converte H (CSV → .npz, com cache)
│   │   ├── processamento_service.py         #   CGNE e CGNR (NumPy/SciPy)
│   │   └── imagem_service.py               #   normalização e geração de PNG
│   └── viewmodels/
│       └── resultado.py                     #   modelos Pydantic de response
│
├── cliente/                                 # Cliente de carga (Python)
│   ├── cliente.py                           #   dispara requisições para ambos os servidores
│   ├── benchmark.py                         #   benchmark com 1/2/4/8 clientes simultâneos
│   └── requirements.txt
│
├── frontend/                                # Dashboard interativo (Streamlit)
│   ├── app.py                               #   3 abas: reconstrução, benchmark, histórico
│   └── requirements.txt
│
├── dados/                                   # Dados de entrada
│   ├── modelo1/                             #   imagem 60×60 px (3 600 pixels, 794 amostras)
│   │   ├── H-1.csv                          #   ⚠ 679 MB — não commitado
│   │   ├── g-60x60-1.csv
│   │   ├── g-60x60-2.csv
│   │   └── A-60x60-1.csv
│   └── modelo2/                             #   imagem 30×30 px (900 pixels, 436 amostras)
│       ├── H-2.csv                          #   ⚠ 109 MB — não commitado
│       ├── g-30x30-1.csv
│       ├── g-30x30-2.csv
│       └── A-30x30-1 (1).csv
│
├── .gitignore
└── README.md
```

> Pastas geradas em tempo de execução (ignoradas pelo git):
> `servidor-python/cache/`, `servidor-python/imagens/`,
> `cliente/relatorios/`, `cliente/benchmark_resultados/`,
> `.venv/` em cada subpasta.

---

## Arquitetura

```
┌──────────────────┐   multipart/form-data   ┌─────────────────────┐
│                  │ ──── (H.csv + g.csv) ──▶│  Servidor C#  :5001 │
│  cliente.py /    │                         │  ASP.NET Core        │
│  frontend        │ ──── (H.csv + g.csv) ──▶│  Servidor Py  :8000 │
│                  │   multipart/form-data   │  FastAPI / Uvicorn   │
└──────────────────┘                         └─────────────────────┘
        │
        │ (subprocesso)
        ▼
┌──────────────────┐
│  Frontend  :8501 │
│  Streamlit       │
└──────────────────┘
```

- O cliente aplica o ganho **γ** no sinal `g` antes de enviar — ambos os servidores recebem o mesmo sinal modificado.
- Os dois servidores expõem **o mesmo contrato de API** (`POST /api/v1/reconstruct`, `multipart/form-data`).
- Cada servidor itera CGNE ou CGNR até `ε < 1×10⁻⁴` **ou** 10 iterações.
- A resposta é um JSON com a imagem reconstruída em **base64 PNG**.

---

## Pré-requisitos

| Componente | Versão mínima |
|------------|---------------|
| .NET SDK   | 10.0          |
| Python     | 3.11+         |

### Instalar .NET no macOS (Apple Silicon)

```bash
brew install dotnet

# Adicione ao ~/.zshrc:
export DOTNET_ROOT=$(brew --prefix)/opt/dotnet/libexec
export PATH="$DOTNET_ROOT:$PATH"

source ~/.zshrc
dotnet --version   # deve exibir 10.x
```

---

## Como Rodar

> Todos os caminhos partem de dentro de `desenvolvimento-integrado-sistemas/`.

### Apresentação completa (3 terminais)

Para a apresentação ao professor, mantenha os 3 terminais abaixo rodando e acesse o frontend no navegador.

---

#### Terminal 1 — Servidor C# (porta 5001)

```bash
cd desenvolvimento-integrado-sistemas
dotnet run --urls "http://0.0.0.0:5001"
```

Aguarde: `Now listening on: http://0.0.0.0:5001`

> Na **primeira** requisição, o servidor converte e faz cache da matriz H em `.mtx` — pode demorar alguns segundos.

---

#### Terminal 2 — Servidor Python (porta 8000)

```bash
cd desenvolvimento-integrado-sistemas/servidor-python
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

Aguarde: `Application startup complete.`

> Na **primeira** requisição, o servidor converte e faz cache da matriz H em `.npz` — pode demorar alguns segundos.

---

#### Terminal 3 — Frontend Streamlit (porta 8501)

```bash
cd desenvolvimento-integrado-sistemas/frontend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Acesse **`http://localhost:8501`** no navegador.

Clique em **"Verificar"** na sidebar para confirmar que ambos os servidores aparecem com bolinha verde.

---

### Cliente de linha de comando (opcional)

Para disparar carga diretamente sem o frontend:

```bash
cd desenvolvimento-integrado-sistemas/cliente
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Exemplo: 2 clientes simultâneos, 5 requisições cada, modelo 2 (30×30, mais rápido)
python3 cliente.py --clientes 2 --rodadas 5 --modelo 2 --algoritmo CGNR
```

| Parâmetro     | Descrição                                    | Padrão    |
|---------------|----------------------------------------------|-----------|
| `--clientes`  | Número de threads simultâneas                | `3`       |
| `--rodadas`   | Requisições por cliente                      | `10`      |
| `--modelo`    | `1` = 60×60 px · `2` = 30×30 px             | aleatório |
| `--algoritmo` | `CGNE` ou `CGNR`                             | aleatório |

Relatório HTML e JSON salvos em `cliente/relatorios/`.

---

### Benchmark automatizado (opcional)

Testa 1, 2, 4 e 8 clientes simultâneos e gera gráficos comparativos de throughput e latência.
Também pode ser disparado pela aba **Benchmark** do frontend.

```bash
cd desenvolvimento-integrado-sistemas/cliente
source .venv/bin/activate
python3 benchmark.py --rodadas 3
```

Resultados em `cliente/benchmark_resultados/`.

---

## API — Contrato de Requisição

### `POST /api/v1/reconstruct`

**Content-Type:** `multipart/form-data`

| Campo             | Tipo   | Descrição                                           |
|-------------------|--------|-----------------------------------------------------|
| `Algoritmo`       | string | `"CGNE"` ou `"CGNR"`                               |
| `ArquivoMatrizCsv`| file   | Matriz H em CSV (formato: `valor,linha,coluna`)     |
| `ArquivoSinalG`   | file   | Sinal g em CSV — nome deve conter `NxM`             |

> O nome do arquivo g **deve** seguir o padrão `g-NxM-*.csv` (ex.: `g-30x30-1.csv`), pois as dimensões da imagem são extraídas do nome.

**Resposta JSON:**

```json
{
  "data": {
    "algoritmoId":          "CGNR",
    "inicioReconstrucao":   "2026-06-14T15:30:00.000Z",
    "terminoReconstrucao":  "2026-06-14T15:30:02.341Z",
    "tamanhoPxAltura":      30,
    "tamanhoPxLargura":     30,
    "iteracoesExecutadas":  7,
    "epsilon":              8.34e-5,
    "imagemBase64":         "iVBORw0KGgo..."
  },
  "errors": []
}
```

---

## Algoritmos

### CGNE — Conjugate Gradient Normal Error

Minimiza `‖Hf − g‖` iterando no espaço de imagem:

```
r₀ = g − H·f₀ ;  p₀ = Hᵀ·r₀
loop:
    α = ‖r‖² / ‖p‖²
    f = f + α·p
    r = r − α·(H·p)
    γ = ‖r_novo‖² / ‖r_ant‖²
    p = Hᵀ·r + γ·p
até: ε = ‖r‖/‖g‖ < 1e-4  ou  10 iterações
```

### CGNR — Conjugate Gradient Normal Residual

Minimiza `‖Hᵀ(Hf − g)‖` iterando no espaço de sinal:

```
r₀ = g − H·f₀ ;  z₀ = Hᵀ·r₀ ;  p₀ = z₀
loop:
    w = H·p
    α = ‖z‖² / ‖w‖²
    f = f + α·p
    r = r − α·w
    z = Hᵀ·r
    γ = ‖z_novo‖² / ‖z_ant‖²
    p = z + γ·p
até: ε = ‖r‖/‖g‖ < 1e-4  ou  10 iterações
```

---

## Ganho de Sinal (aplicado no cliente)

Antes de enviar, o cliente modifica o sinal `g`:

```
γᵢ = 100 + (1/20) · i · √i      (i = 1…S)
g̃  = g · γ                       (broadcasting por linha de amostra)
```

O sinal modificado é enviado **igualmente** para os dois servidores, garantindo que a comparação seja feita nas mesmas condições de entrada.

---

## Cache de Matrizes

| Servidor | Formato  | Localização                                    |
|----------|----------|------------------------------------------------|
| C#       | `.mtx`   | raiz de `desenvolvimento-integrado-sistemas/`  |
| Python   | `.npz`   | `servidor-python/cache/`                       |

Na primeira requisição com uma matriz H nova, o servidor a converte e armazena. Requisições subsequentes usam o cache, reduzindo o tempo de resposta significativamente.

---

## Arquivos grandes (não commitados)

| Arquivo                 | Tamanho | Descrição                    |
|-------------------------|---------|------------------------------|
| `dados/modelo1/H-1.csv` | ~679 MB | Matriz de projeção 60×60 px  |
| `dados/modelo2/H-2.csv` | ~109 MB | Matriz de projeção 30×30 px  |

Estes arquivos devem ser obtidos separadamente e colocados nas pastas corretas antes de executar.

---

## Licença

Projeto acadêmico — UTFPR — Desenvolvimento Integrado de Sistemas.
