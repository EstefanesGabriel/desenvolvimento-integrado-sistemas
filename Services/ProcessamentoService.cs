using MathNet.Numerics.LinearAlgebra;
using MathNet.Numerics.LinearAlgebra.Double;
using MathNet.Numerics.Data.Text;
using System.Globalization;
using ServerDotNet.ViewModels;
using Microsoft.AspNetCore.Http;

namespace ServerDotNet.Services;

public record ResultadoAlgoritmo(Vector<double> VetorF, int Iteracoes);

public class ProcessamentoService
{
    public async Task<ResultViewModel<ResultadoAlgoritmo>> ReconstruirImagemAsync(
        string arquivoMatriz, 
        IFormFile arquivoSinalG, 
        string algoritmo = "CGNR",
        int maxIter = 10, 
        double tol = 1e-4)
    {
        try
        {
            string caminhoMatriz = Path.Combine(Directory.GetCurrentDirectory(), arquivoMatriz);

            if (!File.Exists(caminhoMatriz))
                return new ResultViewModel<ResultadoAlgoritmo>($"Matriz '{arquivoMatriz}' não encontrada.");

            var H = MatrixMarketReader.ReadMatrix<double>(caminhoMatriz);

            var valoresG = new List<double>();
            using (var stream = arquivoSinalG.OpenReadStream())
            using (var reader = new StreamReader(stream))
            {
                string? linhaTexto;
                while ((linhaTexto = await reader.ReadLineAsync()) != null)
                {
                    var partes = linhaTexto.Split(new[] { ',', ';' }, StringSplitOptions.RemoveEmptyEntries);
                    foreach (var parte in partes)
                    {
                        if (double.TryParse(parte, NumberStyles.Float, CultureInfo.InvariantCulture, out double valor))
                            valoresG.Add(valor);
                    }
                }
            }

            var g = Vector<double>.Build.DenseOfEnumerable(valoresG);

            if (H.RowCount != g.Count)
                return new ResultViewModel<ResultadoAlgoritmo>($"Dimensão incompatível: H tem {H.RowCount} linhas, mas g tem {g.Count} elementos.");

            ResultadoAlgoritmo resultado;
            if (algoritmo == "CGNE")
            {
                resultado = ExecutarCGNE(H, g, maxIter, tol);
            }
            else
            {
                resultado = ExecutarCGNR(H, g, maxIter, tol);
            }

            return new ResultViewModel<ResultadoAlgoritmo>(resultado, new List<string>());
        }
        catch (Exception ex)
        {
            return new ResultViewModel<ResultadoAlgoritmo>($"Erro matemático ao processar {algoritmo}: {ex.Message}");
        }
    }

    private ResultadoAlgoritmo ExecutarCGNR(Matrix<double> H, Vector<double> g, int maxIter, double tol)
    {
        var f = Vector<double>.Build.Dense(H.ColumnCount);
        var r = g.Clone();
        var z = H.TransposeThisAndMultiply(r);
        var p = z.Clone();
        
        double norm_z_sq = z.DotProduct(z);
        double erro_atual = r.L2Norm();
        int iteracoesExecutadas = 0;

        for (int i = 0; i < maxIter; i++)
        {
            iteracoesExecutadas = i + 1;
            var w = H.Multiply(p);
            double norm_w_sq = w.DotProduct(w);
            
            if (norm_w_sq == 0) break;
            
            double alpha = norm_z_sq / norm_w_sq;
            f = f + (alpha * p);
            r = r - (alpha * w);
            
            erro_atual = r.L2Norm();
            if (erro_atual < tol) break;

            var z_new = H.TransposeThisAndMultiply(r);
            double norm_z_new_sq = z_new.DotProduct(z_new);
            
            if (norm_z_sq == 0) break;
            
            double beta = norm_z_new_sq / norm_z_sq;
            p = z_new + (beta * p);
            norm_z_sq = norm_z_new_sq;
        }

        return new ResultadoAlgoritmo(f, iteracoesExecutadas);
    }

    private ResultadoAlgoritmo ExecutarCGNE(Matrix<double> H, Vector<double> g, int maxIter, double tol)
    {
        var f = Vector<double>.Build.Dense(H.ColumnCount);
        var r = g.Clone();
        var p = H.TransposeThisAndMultiply(r);
        
        double norm_r_sq = r.DotProduct(r);
        double erro_atual = r.L2Norm();
        int iteracoesExecutadas = 0;

        for (int i = 0; i < maxIter; i++)
        {
            iteracoesExecutadas = i + 1;
            double norm_p_sq = p.DotProduct(p);
            
            if (norm_p_sq == 0) break;
            
            double alpha = norm_r_sq / norm_p_sq;
            f = f + (alpha * p);
            
            var Hp = H.Multiply(p);
            r = r - (alpha * Hp);
            
            erro_atual = r.L2Norm();
            if (erro_atual < tol) break;

            double norm_r_new_sq = r.DotProduct(r);
            
            if (norm_r_sq == 0) break;
            
            double beta = norm_r_new_sq / norm_r_sq;
            var HTr = H.TransposeThisAndMultiply(r);
            p = HTr + (beta * p);
            norm_r_sq = norm_r_new_sq;
        }

        return new ResultadoAlgoritmo(f, iteracoesExecutadas);
    }
}