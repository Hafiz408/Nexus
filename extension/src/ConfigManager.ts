import * as vscode from 'vscode';
import { BackendClient } from './BackendClient';

const PROVIDERS = ['openai', 'mistral', 'anthropic', 'ollama', 'gemini'] as const;

export class ConfigManager {
  constructor(
    private readonly context: vscode.ExtensionContext,
    private readonly client: BackendClient,
  ) {}

  async pushConfig(dbPath?: string): Promise<{ reindex_required: boolean }> {
    const config = vscode.workspace.getConfiguration('nexus');
    const chatProvider = config.get<string>('chatProvider', 'mistral');
    const chatModel = config.get<string>('chatModel', 'mistral-small-latest');
    const embeddingProvider = config.get<string>('embeddingProvider', 'mistral');
    const embeddingModel = config.get<string>('embeddingModel', 'mistral-embed');
    const ollamaBaseUrl = config.get<string>('ollamaBaseUrl', 'http://localhost:11434');

    // Gather all API keys from SecretStorage
    const apiKeys: Record<string, string> = {};
    for (const provider of PROVIDERS) {
      const key = await this.context.secrets.get(`nexus.apiKey.${provider}`);
      if (key) {
        apiKeys[provider] = key;
      }
    }

    const body: Record<string, unknown> = {
      chat_provider: chatProvider,
      chat_model: chatModel,
      embedding_provider: embeddingProvider,
      embedding_model: embeddingModel,
      ollama_base_url: ollamaBaseUrl,
      api_keys: apiKeys,
    };
    if (dbPath) {
      body.db_path = dbPath;
    }

    return this.client.postConfig(body);
  }

  async setApiKey(): Promise<void> {
    const provider = await vscode.window.showQuickPick(
      [...PROVIDERS],
      { placeHolder: 'Select provider to configure' }
    );
    if (!provider) { return; }

    const key = await vscode.window.showInputBox({
      prompt: `Enter API key for ${provider}`,
      password: true,
      ignoreFocusOut: true,
    });
    if (!key) { return; }

    await this.context.secrets.store(`nexus.apiKey.${provider}`, key);
    vscode.window.showInformationMessage(`Nexus: API key stored for ${provider}`);
    await this.pushConfig();
  }

  async clearApiKey(): Promise<void> {
    const provider = await vscode.window.showQuickPick(
      [...PROVIDERS],
      { placeHolder: 'Select provider to clear' }
    );
    if (!provider) { return; }
    await this.context.secrets.delete(`nexus.apiKey.${provider}`);
    vscode.window.showInformationMessage(`Nexus: API key cleared for ${provider}`);
    await this.pushConfig();
  }
}
