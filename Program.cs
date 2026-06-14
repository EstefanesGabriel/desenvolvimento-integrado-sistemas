using Microsoft.AspNetCore.Http.Features;
using ServerDotNet.Services;

var builder = WebApplication.CreateBuilder(args);

builder.WebHost.ConfigureKestrel(options =>
{
    options.Limits.MaxRequestBodySize = null; 
});

// IISServerOptions só existe no Windows — ignorado no macOS/Linux

builder.Services.Configure<FormOptions>(options =>
{
    options.ValueLengthLimit = int.MaxValue;
    options.MultipartBodyLengthLimit = long.MaxValue; 
    options.MemoryBufferThreshold = int.MaxValue;
});

builder.Services.AddControllers();

builder.Services.AddSingleton<MatrizService>();
builder.Services.AddSingleton<ProcessamentoService>();
builder.Services.AddSingleton<ImagemService>();

var app = builder.Build();

app.Use(async (context, next) =>
{
    var feature = context.Features.Get<IHttpMaxRequestBodySizeFeature>();
    if (feature != null)
    {
        feature.MaxRequestBodySize = null; 
    }
    await next.Invoke();
});

app.MapControllers();

app.Run();