import { vueTsConfigs, withVueTs } from "@vue/eslint-config-typescript";
import pluginVue from "eslint-plugin-vue";

export default withVueTs(
  pluginVue.configs["flat/essential"],
  vueTsConfigs.recommended,
);
