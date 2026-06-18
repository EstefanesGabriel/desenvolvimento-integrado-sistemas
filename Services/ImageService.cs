using SixLabors.ImageSharp;
using SixLabors.ImageSharp.PixelFormats;
using ServerDotNet.ViewModels;

namespace ServerDotNet.Services;

// Pacote para transportar o nome do arquivo e o Base64 direto da memória
public record ResultadoImagem(string NomeArquivo, string Base64);

public class ImagemService
{
    public ResultViewModel<ResultadoImagem> GerarEGuardarImagem(double[] f_img, int largura, int altura, string nomeArquivoFinal)
    {
        try
        {
            if (f_img.Length != largura * altura)
            {
                return new ResultViewModel<ResultadoImagem>("O tamanho do vetor matemático não corresponde às dimensões calculadas da imagem.");
            }

            double max = f_img.Max();
            double min = f_img.Min();
            double range = max - min;
            if (range == 0) range = 1; 

            using var image = new Image<L8>(largura, altura);

            for (int y = 0; y < altura; y++)
            {
                for (int x = 0; x < largura; x++)
                {
                    int index = x * altura + y; 
                    byte valorPixel = (byte)(((f_img[index] - min) / range) * 255.0);
                    image[x, y] = new L8(valorPixel);
                }
            }
            
            // Salva fisicamente no disco para o cache
            string caminhoCompleto = Path.Combine(Directory.GetCurrentDirectory(), nomeArquivoFinal);
            image.SaveAsPng(caminhoCompleto);

            // Converte para Base64 direto da memória, sem ler o disco de novo!
            string base64String = string.Empty;
            using (var ms = new MemoryStream())
            {
                image.SaveAsPng(ms);
                byte[] bytesImagem = ms.ToArray();
                base64String = Convert.ToBase64String(bytesImagem);
            }

            var resultado = new ResultadoImagem(nomeArquivoFinal, base64String);
            return new ResultViewModel<ResultadoImagem>(resultado, new List<string>());
        }
        catch (Exception ex)
        {
            return new ResultViewModel<ResultadoImagem>($"Erro ao processar imagem na memória: {ex.Message}");
        }
    }
}