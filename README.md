# AutoCommiter

Aplicativo Windows para monitorar um arquivo específico e registrar alterações reais em um repositório Git por meio de commits automáticos.

## O que ele faz

- monitora um arquivo configurado;
- espelha a versão mais recente desse arquivo para dentro de um repositório Git;
- cria um commit apenas quando detecta mudança real no conteúdo ou remoção do arquivo;
- pode fazer `push` automático quando o repositório tiver remoto configurado;
- instala inicialização automática via Agendador de Tarefas do Windows;
- oferece uma interface gráfica com sidebar para `Dashboard` e `Arquivo monitorado`.
- pode auto-descobrir a nota diária atual por pasta no formato `dd-mm-aaaa.md`.
- pode verificar novas versões via `GitHub Releases`, baixar o asset e pedir reinício para aplicar.

## Requisitos

- Windows com PowerShell;
- Python 3.11+;
- Git configurado com identidade de commit no repositório de destino.

## Instalação única

```powershell
.\scripts\install.ps1 `
  -WatchedFile "C:\caminho\arquivo.txt" `
  -RepositoryPath "C:\caminho\repo-privado" `
  -PushOnCommit
```

O instalador:

- cria `.venv`;
- instala o pacote;
- salva a configuração em `%APPDATA%\AutoCommiter\config.json`;
- registra a tarefa `AutoCommiter` para iniciar no login.

## Uso manual

```powershell
.venv\Scripts\python -m autocommiter configure `
  --watched-file "C:\caminho\arquivo.txt" `
  --repository-path "C:\caminho\repo-privado" `
  --daily-notes-directory "C:\Users\paulo\OneDrive\Documentos\Obsidian Vault\Estudos Diários" `
  --update-repository "owner/AutoCommiter" `
  --max-detections-per-day 100 `
  --push-on-commit

.venv\Scripts\python -m autocommiter run
```

## Interface gráfica

```powershell
.venv\Scripts\python -m autocommiter gui
```

### Dashboard

- define o máximo de detecções de mudança no dia;
- mostra quantas mudanças já foram detectadas hoje;
- mostra quantos commits de mudança já foram feitos hoje.

Quando atingir o limite diário, o monitoramento deixa de registrar novas mudanças até o próximo dia.

### Arquivo monitorado

- permite arrastar e soltar o arquivo a ser monitorado;
- permite informar a pasta de notas diárias para descobrir automaticamente a nota do dia;
- mostra o status atual do monitoramento;
- permite salvar o caminho do repositório de destino;
- permite randomizar o número gravado no arquivo monitorado.

### Inicialização automática

- a tarefa do Windows agora inicia a interface gráfica já minimizada;
- a interface continua monitorando em segundo plano após o login.

### Auto-update

- configure no `Dashboard` o repositório `owner/repo` das releases do app;
- ao abrir a interface, o app verifica se existe release mais nova;
- se existir, mostra prompt para download;
- depois do download, mostra prompt para reiniciar e aplicar a atualização.

## Validação

```powershell
.\scripts\validate.ps1
```
