using SixLabors.ImageSharp;
using SixLabors.ImageSharp.PixelFormats;
using ServerDotNet.ViewModels;

namespace ServerDotNet.Services;

public class ImagemService
{
    public ResultViewModel<string> GerarEGuardarImagem(double[] f_img, int largura, int altura, string nomeArquivoFinal)
    {
        try
        {
            if (f_img.Length != largura * altura)
            {
                return new ResultViewModel<string>("O tamanho do vetor matemático não corresponde às dimensões calculadas da imagem.");
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
            
            string caminhoCompleto = Path.Combine(Directory.GetCurrentDirectory(), nomeArquivoFinal);
            image.SaveAsPng(caminhoCompleto);

            return new ResultViewModel<string>(nomeArquivoFinal, new List<string>());
        }
        catch (Exception ex)
        {
            return new ResultViewModel<string>($"Erro ao salvar arquivo PNG: {ex.Message}");
        }
    }
}