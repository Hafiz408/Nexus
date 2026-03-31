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

  /** Returns provider names that are configured but missing a stored key. */
  async getMissingProviders(): Promise<string[]> {
    const config = vscode.workspace.getConfiguration('nexus');
    const chatProvider = config.get<string>('chatProvider', 'mistral');
    const embeddingProvider = config.get<string>('embeddingProvider', 'mistral');
    const needed = [...new Set([chatProvider, embeddingProvider])].filter(p => p !== 'ollama');

    const missing: string[] = [];
    for (const provider of needed) {
      const key = await this.context.secrets.get(`nexus.apiKey.${provider}`);
      if (!key) { missing.push(provider); }
    }
    return missing;
  }

  /**
   * Prompt for API keys that are required by the current config but not yet stored.
   * Deduplicates providers (chat == embedding → one prompt) and skips Ollama (no key needed).
   * Used by the first-run welcome flow.
   */
  async setupMissingKeys(): Promise<void> {
    const config = vscode.workspace.getConfiguration('nexus');
    const chatProvider = config.get<string>('chatProvider', 'mistral');
    const embeddingProvider = config.get<string>('embeddingProvider', 'mistral');

    const needed = [...new Set([chatProvider, embeddingProvider])].filter(p => p !== 'ollama');

    for (const provider of needed) {
      const existing = await this.context.secrets.get(`nexus.apiKey.${provider}`);
      if (existing) { continue; }

      const key = await vscode.window.showInputBox({
        title: `Nexus: API Key for ${provider}`,
        prompt: `Enter your ${provider} API key`,
        password: true,
        ignoreFocusOut: true,
      });
      if (!key) { continue; }

      await this.context.secrets.store(`nexus.apiKey.${provider}`, key);
      vscode.window.showInformationMessage(`Nexus: API key stored for ${provider}`);
    }

    await this.pushConfig();
  }

  /** Build a role-aware QuickPick item list showing configured providers first. */
  private async _buildProviderItems(): Promise<(vscode.QuickPickItem & { provider: string })[]> {
    const config = vscode.workspace.getConfiguration('nexus');
    const chatProvider = config.get<string>('chatProvider', 'mistral');
    const embeddingProvider = config.get<string>('embeddingProvider', 'mistral');

    type Item = vscode.QuickPickItem & { provider: string };
    const items: Item[] = [];

    // ── Active providers (what the user has configured) ──────────────────
    const activeSet = new Set([chatProvider, embeddingProvider]);
    for (const provider of activeSet) {
      if (provider === 'ollama') { continue; } // Ollama is local — no key needed
      const hasKey = !!(await this.context.secrets.get(`nexus.apiKey.${provider}`));
      const roles: string[] = [];
      if (provider === chatProvider) { roles.push('Chat LLM'); }
      if (provider === embeddingProvider) { roles.push('Embeddings'); }
      items.push({
        label: provider,
        description: roles.join(' & '),
        detail: hasKey ? '$(check) Key stored' : '$(warning) No key stored',
        provider,
      });
    }

    // ── Other providers ───────────────────────────────────────────────────
    const others = PROVIDERS.filter(p => !activeSet.has(p) && p !== 'ollama');
    if (others.length > 0) {
      items.push({ label: 'Other providers', kind: vscode.QuickPickItemKind.Separator, provider: '' });
      for (const p of others) {
        const hasKey = !!(await this.context.secrets.get(`nexus.apiKey.${p}`));
        items.push({
          label: p,
          description: 'not currently configured',
          detail: hasKey ? '$(check) Key stored' : undefined,
          provider: p,
        });
      }
    }

    return items;
  }

  async setApiKey(): Promise<void> {
    const items = await this._buildProviderItems();
    const picked = await vscode.window.showQuickPick(items, {
      placeHolder: 'Select provider to set API key',
      matchOnDescription: true,
    });
    if (!picked?.provider) { return; }

    const roleHint = picked.description && !picked.description.includes('not currently')
      ? ` (${picked.description})`
      : '';
    const key = await vscode.window.showInputBox({
      title: `Nexus: Set API Key — ${picked.label}${roleHint}`,
      prompt: `Enter your ${picked.label} API key`,
      password: true,
      ignoreFocusOut: true,
    });
    if (!key) { return; }

    await this.context.secrets.store(`nexus.apiKey.${picked.provider}`, key);
    vscode.window.showInformationMessage(`Nexus: API key stored for ${picked.label}`);
    await this.pushConfig();
  }

  async clearApiKey(): Promise<void> {
    const items = await this._buildProviderItems();
    const withKeys = items.filter(i => i.detail?.includes('$(check)'));
    if (withKeys.length === 0) {
      vscode.window.showInformationMessage('Nexus: No API keys are currently stored.');
      return;
    }

    const picked = await vscode.window.showQuickPick(withKeys, {
      placeHolder: 'Select provider to clear API key',
      matchOnDescription: true,
    });
    if (!picked?.provider) { return; }

    await this.context.secrets.delete(`nexus.apiKey.${picked.provider}`);
    vscode.window.showInformationMessage(`Nexus: API key cleared for ${picked.label}`);
    await this.pushConfig();
  }
}
