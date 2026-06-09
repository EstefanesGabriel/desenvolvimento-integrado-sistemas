using MathNet.Numerics.LinearAlgebra.Double;
using MathNet.Numerics.Data.Text;
using System.Globalization;
using ServerDotNet.ViewModels;
using Microsoft.AspNetCore.Http;

namespace ServerDotNet.Services;

public class MatrizService
{
    public async Task<ResultViewModel<string>> ObterOuConverterMatrizAsync(IFormFile arquivoCsv)
    {
        // Define o nome esperado baseado no arquivo enviado (ex: H-1-convertida.mtx)
        string nomeOriginal = Path.GetFileNameWithoutExtension(arquivoCsv.FileName);
        string nomeArquivoMtx = $"{nomeOriginal}-convertida.mtx";
        string caminhoCompleto = Path.Combine(Directory.GetCurrentDirectory(), nomeArquivoMtx);

        // CRITÉRIO DE CACHE: Se o arquivo .mtx já existe no disco, não processa de novo!
        if (File.Exists(caminhoCompleto))
        {
            return new ResultViewModel<string>(nomeArquivoMtx, new List<string>());
        }

        var valoresNaoNulos = new List<Tuple<int, int, double>>();
        int linhas = 0;
        int colunas = 0;

        try
        {
            using (var stream = arquivoCsv.OpenReadStream())
            using (var reader = new StreamReader(stream))
            {
                string? linhaTexto;
                while ((linhaTexto = await reader.ReadLineAsync()) != null)
                {
                    var valoresLinha = linhaTexto.Split(',');
                    colunas = valoresLinha.Length;

                    for (int c = 0; c < colunas; c++)
                    {
                        if (double.TryParse(valoresLinha[c], NumberStyles.Float, CultureInfo.InvariantCulture, out double valor))
                        {
                            if (valor != 0.0) 
                            {
                                valoresNaoNulos.Add(new Tuple<int, int, double>(linhas, c, valor));
                            }
                        }
                    }
                    linhas++;
                }
            }

            var matrizEsparsa = SparseMatrix.OfIndexed(linhas, colunas, valoresNaoNulos);
            MatrixMarketWriter.WriteMatrix(caminhoCompleto, matrizEsparsa);

            return new ResultViewModel<string>(nomeArquivoMtx, new List<string>());
        }
        catch (Exception ex)
        {
            return new ResultViewModel<string>($"Falha interna ao converter matriz: {ex.Message}");
        }
    }
}