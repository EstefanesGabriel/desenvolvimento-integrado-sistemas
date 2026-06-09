namespace ServerDotNet.ViewModels;

public class DadosReconstrucao
{
    public string Mensagem { get; set; } = string.Empty;
    public string ArquivoImagem { get; set; } = string.Empty;
    public string AlgoritmoUtilizado { get; set; } = string.Empty;
    public string InicioReconstrucao { get; set; } = string.Empty;
    public string TerminoReconstrucao { get; set; } = string.Empty;
    public string TamanhoPixels { get; set; } = string.Empty;
    public int IteracoesExecutadas { get; set; }
}