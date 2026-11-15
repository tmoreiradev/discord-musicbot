# "Sign in to confirm you're not a bot" em UM video (o controle passa pelo mesmo WARP) era
# tratado como erro generico: o player ficava PAUSED sem audio e a fila parava ali, inclusive
# o que o /radio enfileirava depois (2026-10-03, hmpJqJLsR48). Classifica como indisponivel,
# entao o player pula a faixa como faz com video removido/privado.
/\/video unavailable\/i,/a\        /sign in to confirm you.re not a bot/i,
# "Please sign in" = video que exige login para qualquer IP (w1oM3kQpXRo falha ate pelo IP de casa)
/\/video unavailable\/i,/a\        /please sign in\./i,
