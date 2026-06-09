using Microsoft.AspNetCore.Http;
using System.ComponentModel.DataAnnotations;

namespace ServerDotNet.ViewModels;

public class RequisicaoUnificada
{
    [Required(ErrorMessage = "O arquivo CSV da Matriz (H) é obrigatório.")]
    public IFormFile ArquivoMatrizCsv { get; set; } = null!;

    [Required(ErrorMessage = "O arquivo CSV do Sinal (G) é obrigatório.")]
    public IFormFile ArquivoSinalG { get; set; } = null!;

    public string Algoritmo { get; set; } = "CGNR"; 
}