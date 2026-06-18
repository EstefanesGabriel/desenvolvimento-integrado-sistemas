using Microsoft.AspNetCore.Mvc;
using ServerDotNet.Services;
using ServerDotNet.ViewModels;
using System.Text.RegularExpressions;

namespace ServerDotNet.Controllers;

[ApiController]
public class ProcessamentoUnificadoController : ControllerBase
{
    [HttpPost("api/v1/reconstruct")]
    [DisableRequestSizeLimit]
    [RequestFormLimits(ValueLengthLimit = int.MaxValue, MultipartBodyLengthLimit = long.MaxValue)]
    public async Task<IActionResult> ProcessarTudo(
        [FromForm] RequisicaoUnificada requisicao,
        [FromServices] MatrizService matrizService,
        [FromServices] ProcessamentoService procService,
        [FromServices] ImagemService imagemService)
    {
        if (requisicao.ArquivoMatrizCsv == null || requisicao.ArquivoMatrizCsv.Length == 0)
            return BadRequest(new ResultViewModel<string>("O arquivo CSV da Matriz H é obrigatório."));

        if (requisicao.ArquivoSinalG == null || requisicao.ArquivoSinalG.Length == 0)
            return BadRequest(new ResultViewModel<string>("O arquivo CSV do Sinal G é obrigatório."));

        string algoritmo = requisicao.Algoritmo?.ToUpper() == "CGNE" ? "CGNE" : "CGNR";

        // Conversão/Cache da Matriz H
        var resultadoMatriz = await matrizService.ObterOuConverterMatrizAsync(requisicao.ArquivoMatrizCsv);
        if (resultadoMatriz.Errors.Any())
            return BadRequest(resultadoMatriz);

        string nomeArquivoMtx = resultadoMatriz.Data!;

        // Extração dos padrões do nome do arquivo de sinal
        string nomeSinalCompleto = requisicao.ArquivoSinalG.FileName ?? "";
        var matchSinal = Regex.Match(nomeSinalCompleto, @"\d+x\d+-\d+"); 

        if (!matchSinal.Success)
        {
            matchSinal = Regex.Match(nomeSinalCompleto, @"\d+x\d+");
            if (!matchSinal.Success)
                return BadRequest(new ResultViewModel<string>("O nome do arquivo de sinal deve conter o padrão de dimensão (ex: g-60x60-1.csv)."));
        }

        string sufixoSinal = matchSinal.Value; 
        string nomeImagemFinal = $"imagem-{sufixoSinal}-{algoritmo}.png";

        var matchDimensoes = Regex.Match(sufixoSinal, @"\d+x\d+");
        var partes = matchDimensoes.Value.Split('x');
        int largura = int.Parse(partes[0]);
        int altura = int.Parse(partes[1]);
        string strPixels = $"{largura}x{altura}";

        // Execução Matemática (CGNR ou CGNE) com marcação de tempo
        DateTime tempoInicio = DateTime.Now;
        var resultadoProcessamento = await procService.ReconstruirImagemAsync(nomeArquivoMtx, requisicao.ArquivoSinalG, algoritmo);
        DateTime tempoTermino = DateTime.Now;

        if (resultadoProcessamento.Errors.Any())
        {
            var erroResult = new ResultViewModel<DadosReconstrucao>(resultadoProcessamento.Errors.First());
            return BadRequest(erroResult);
        }

        var dadosAlgoritmo = resultadoProcessamento.Data!;
        double[] pixels = dadosAlgoritmo.VetorF.ToArray();
        int totalIteracoes = dadosAlgoritmo.Iteracoes;

        // PASSO 3: Pintura e gravação física da imagem PNG
        var resultadoImagem = imagemService.GerarEGuardarImagem(pixels, largura, altura, nomeImagemFinal);
        if (resultadoImagem.Errors.Any())
        {
            var erroImgResult = new ResultViewModel<DadosReconstrucao>(resultadoImagem.Errors.First());
            return StatusCode(500, erroImgResult);
        }

        // Montagem do objeto DadosReconstrucao estruturado do novo arquivo
        var dadosSucesso = new DadosReconstrucao
        {
            Mensagem = "Processamento completo e imagem gerada com sucesso!",
            ArquivoImagem = resultadoImagem.Data!.NomeArquivo,
            ImagemBase64 = resultadoImagem.Data!.Base64,
            AlgoritmoUtilizado = algoritmo,
            InicioReconstrucao = tempoInicio.ToString("dd/MM/yyyy HH:mm:ss.fff"),
            TerminoReconstrucao = tempoTermino.ToString("dd/MM/yyyy HH:mm:ss.fff"),
            TamanhoPixels = strPixels,
            IteracoesExecutadas = totalIteracoes
        };

        return Ok(new ResultViewModel<DadosReconstrucao>(dadosSucesso));
    }
}