"""流体物性计算核心逻辑。"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Callable, Dict, List, Optional, Tuple


INPUT_KEY_MAP: Dict[str, Tuple[str, float]] = {
    "T": ("T", 1.0),
    "P": ("P", 1000.0),
    "H": ("Hmass", 1000.0),
    "S": ("Smass", 1000.0),
    "D": ("Dmass", 1.0),
    "Q": ("Q", 1.0),
}

OUTPUT_KEY_MAP: Dict[str, Tuple[str, float]] = {
    "T": ("T", 1.0),
    "P": ("P", 1.0 / 1000.0),
    "H": ("Hmass", 1.0 / 1000.0),
    "S": ("Smass", 1.0 / 1000.0),
    "D": ("Dmass", 1.0),
    "Q": ("Q", 1.0),
}

UNIT_HINTS: Dict[str, str] = {
    "T": "K",
    "P": "kPa",
    "H": "kJ/kg",
    "S": "kJ/(kg*K)",
    "D": "kg/m^3",
    "Q": "quality(0-1)",
}

PHASE_LABELS: Dict[int, str] = {
    0: "liquid",
    1: "supercritical",
    2: "supercritical_gas",
    3: "supercritical_liquid",
    4: "critical_point",
    5: "gas",
    6: "two_phase",
    7: "unknown",
}

FLUID_ALIASES: Dict[str, str] = {
    "water": "Water",
    "steam": "Water",
    "h2o": "Water",
    "水": "Water",
    "水蒸气": "Water",
    "蒸汽": "Water",
    "空气": "Air",
    "air": "Air",
    "r134a": "R134a",
    "ammonia": "Ammonia",
    "nh3": "Ammonia",
    "co2": "CO2",
    "carbon dioxide": "CO2",
}

OUTPUT_ALIASES: Dict[str, str] = {
    "h": "H",
    "enthalpy": "H",
    "比焓": "H",
    "焓": "H",
    "s": "S",
    "entropy": "S",
    "比熵": "S",
    "熵": "S",
    "t": "T",
    "temperature": "T",
    "温度": "T",
    "p": "P",
    "pressure": "P",
    "压力": "P",
    "d": "D",
    "density": "D",
    "密度": "D",
    "q": "Q",
    "quality": "Q",
    "干度": "Q",
}

INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "fluid": {"type": "string", "description": "工质名称，例如 Water、R134a、Air"},
        "inputs": {
            "type": "object",
            "description": "两个已知状态量，例如 {'T': 300, 'P': 101.325}",
        },
        "outputs": {
            "type": "array",
            "description": "待求物性列表，例如 ['H', 'S']",
        },
        "query": {
            "type": "string",
            "description": "自然语言问题，可替代结构化输入。",
        },
    },
}


def load_props_si() -> Callable[..., float]:
    """延迟加载 CoolProp。"""
    try:
        from CoolProp.CoolProp import PropsSI
    except ImportError as exc:
        raise RuntimeError(
            "当前环境未安装 CoolProp，请先执行 `pip install CoolProp==7.2.0`。"
        ) from exc
    return PropsSI


class FluidPropertyEngine:
    """独立服务与主应用共享的流体物性计算引擎。"""

    def __init__(self, props_loader: Callable[[], Callable[..., float]] | None = None) -> None:
        """初始化计算引擎。"""
        self._props_loader = props_loader or load_props_si

    def _canonicalize_fluid_name(self, fluid: Any) -> str:
        """将工质名称归一化。"""
        normalized = str(fluid or "").strip()
        if not normalized:
            return ""
        lowered = normalized.lower()
        if lowered in FLUID_ALIASES:
            return FLUID_ALIASES[lowered]
        for alias, canonical in sorted(FLUID_ALIASES.items(), key=lambda item: -len(item[0])):
            if alias in lowered:
                return canonical
        return normalized

    def _canonicalize_outputs(self, outputs: Any) -> List[str]:
        """统一输出量名称。"""
        normalized_outputs: List[str] = []
        if not isinstance(outputs, list):
            return normalized_outputs
        for item in outputs:
            output_text = str(item or "").strip()
            if not output_text:
                continue
            upper_output = output_text.upper()
            if upper_output in OUTPUT_KEY_MAP and upper_output not in normalized_outputs:
                normalized_outputs.append(upper_output)
                continue
            lowered_output = output_text.lower()
            mapped_output = OUTPUT_ALIASES.get(lowered_output)
            if mapped_output and mapped_output not in normalized_outputs:
                normalized_outputs.append(mapped_output)
        return normalized_outputs

    def _normalize_candidate_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """规范化候选输入。"""
        normalized_payload: Dict[str, Any] = {}
        fluid = self._canonicalize_fluid_name(payload.get("fluid"))
        if fluid:
            normalized_payload["fluid"] = fluid

        raw_inputs = payload.get("inputs", {})
        if isinstance(raw_inputs, dict):
            normalized_inputs: Dict[str, float] = {}
            for key in ("T", "P", "H", "S", "D", "Q"):
                if key not in raw_inputs:
                    continue
                try:
                    normalized_inputs[key] = float(raw_inputs[key])
                except (TypeError, ValueError):
                    continue
            if normalized_inputs:
                normalized_payload["inputs"] = dict(list(normalized_inputs.items())[:2])

        outputs = self._canonicalize_outputs(payload.get("outputs", []))
        if outputs:
            normalized_payload["outputs"] = outputs

        return normalized_payload

    def _extract_json_object(self, text: str) -> Dict[str, Any]:
        """从文本中抽取 JSON。"""
        if not isinstance(text, str):
            return {}
        stripped = text.strip()
        if not stripped:
            return {}
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
        match = re.search(r"(\{.*\})", stripped, re.DOTALL)
        if not match:
            return {}
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return {}

    def _build_llm_fallback_prompt(self, query: str) -> str:
        """构造 LLM 兜底提示词。"""
        supported_fluids = sorted(set(FLUID_ALIASES.values()))
        return f"""
你是流体热物性计算参数提取器。请从用户问题中提取工质、两个已知状态量和目标输出量。

要求：
1. 只输出一个 JSON 对象，不要输出解释。
2. fluid 只能使用以下标准名称之一：{supported_fluids}
3. inputs 只能包含且必须包含两个键，键只能是 T、P、H、S、D、Q。
4. outputs 必须是非空数组，元素只能是 T、P、H、S、D、Q。
5. 单位统一为：T(K)、P(kPa)、H(kJ/kg)、S(kJ/(kg*K))、D(kg/m^3)、Q(0-1)。
6. 只有当用户问题中信息明确时才提取；不明确的字段留空。
7. confidence 取 0 到 1 之间的小数。

输出格式：
{{
  "fluid": "",
  "inputs": {{}},
  "outputs": [],
  "confidence": 0.0
}}

用户问题：
{query}
""".strip()

    def _extract_with_llm_fallback(self, query: str) -> Dict[str, Any]:
        """规则解析不足时，使用 LLM 做受限结构化补全。"""
        try:
            from graphrag_agent.models.get_models import get_llm_model
        except Exception:
            return {}

        try:
            llm = get_llm_model()
            response = llm.invoke(self._build_llm_fallback_prompt(query))
        except Exception:
            return {}

        content = response.content if hasattr(response, "content") else response
        parsed = self._extract_json_object(str(content))
        if not isinstance(parsed, dict):
            return {}
        try:
            confidence = float(parsed.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < 0.6:
            return {}
        return self._normalize_candidate_payload(parsed)

    def _extract_from_query(self, query: str) -> Dict[str, Any]:
        """从自然语言查询中提取结构化参数。"""
        if not isinstance(query, str) or not query.strip():
            return {}

        text = query.strip()
        lowered = text.lower()
        fluid = ""
        for alias, canonical in sorted(FLUID_ALIASES.items(), key=lambda item: -len(item[0])):
            if alias in lowered:
                fluid = canonical
                break

        inputs: Dict[str, float] = {}
        patterns = {
            "T": r"(?i)\bT\s*=\s*([-+]?\d+(?:\.\d+)?)\s*K\b|温度\s*[=:：]?\s*([-+]?\d+(?:\.\d+)?)\s*K",
            "P": r"(?i)\bP\s*=\s*([-+]?\d+(?:\.\d+)?)\s*kPa\b|压力\s*[=:：]?\s*([-+]?\d+(?:\.\d+)?)\s*kPa",
            "H": r"(?i)\bH\s*=\s*([-+]?\d+(?:\.\d+)?)\s*kJ\s*/\s*kg\b|比焓\s*[=:：]?\s*([-+]?\d+(?:\.\d+)?)",
            "S": r"(?i)\bS\s*=\s*([-+]?\d+(?:\.\d+)?)\s*kJ\s*/\s*\(\s*kg(?:\*|·)?K\s*\)\b|比熵\s*[=:：]?\s*([-+]?\d+(?:\.\d+)?)",
            "D": r"(?i)\bD\s*=\s*([-+]?\d+(?:\.\d+)?)\s*kg\s*/\s*m\^?3\b|密度\s*[=:：]?\s*([-+]?\d+(?:\.\d+)?)",
            "Q": r"(?i)\bQ\s*=\s*([-+]?\d+(?:\.\d+)?)\b|干度\s*[=:：]?\s*([-+]?\d+(?:\.\d+)?)",
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, text)
            if match:
                value = next((group for group in match.groups() if group is not None), None)
                if value is not None:
                    inputs[key] = float(value)

        outputs: List[str] = []
        ask_match = re.search(
            r"(?i)(?:求|计算|calculate|get|obtain|determine).*?(?:下的|for|:)?\s*([A-Za-z,\s和及与、比焓比熵温度压力密度干度entropyenthalpydensityqualityTHSPDQ]+)$",
            text,
        )
        if ask_match:
            ask_text_raw = ask_match.group(1).strip()
            ask_text = ask_text_raw.lower()
            for symbol in re.findall(r"\b([THSPDQ])\b", ask_text_raw, flags=re.IGNORECASE):
                canonical = symbol.upper()
                if canonical not in outputs:
                    outputs.append(canonical)
            for alias, canonical in OUTPUT_ALIASES.items():
                if alias in ask_text and canonical not in outputs:
                    outputs.append(canonical)
        else:
            for alias, canonical in OUTPUT_ALIASES.items():
                if alias in lowered and canonical not in outputs:
                    outputs.append(canonical)

        result: Dict[str, Any] = {}
        if fluid:
            result["fluid"] = fluid
        if len(inputs) >= 2:
            ordered_inputs = {}
            for key in ("T", "P", "H", "S", "D", "Q"):
                if key in inputs:
                    ordered_inputs[key] = inputs[key]
            result["inputs"] = dict(list(ordered_inputs.items())[:2])
        if outputs:
            result["outputs"] = outputs

        if result.get("fluid") and result.get("inputs") and result.get("outputs"):
            return result

        llm_result = self._extract_with_llm_fallback(text)
        if not llm_result:
            return result

        merged_result = dict(result)
        for key in ("fluid", "inputs", "outputs"):
            if not merged_result.get(key) and llm_result.get(key):
                merged_result[key] = llm_result[key]
        return merged_result

    def normalize_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """规范化输入请求。"""
        payload = request
        if not isinstance(payload, dict):
            raise ValueError("request 必须是字典")

        nested_payload = payload.get("query") or payload.get("input")
        if isinstance(nested_payload, dict):
            payload = nested_payload
        elif isinstance(nested_payload, str):
            extracted_payload = self._extract_from_query(nested_payload)
            payload = {**payload, **extracted_payload}

        payload = self._normalize_candidate_payload(payload)

        fluid = str(payload.get("fluid", "")).strip()
        inputs = payload.get("inputs", {})
        outputs = payload.get("outputs", [])

        if not fluid:
            raise ValueError("fluid 不能为空")
        if not isinstance(inputs, dict) or len(inputs) != 2:
            raise ValueError("inputs 必须且只能提供两个状态参数，例如 {'T': 300, 'P': 101.325}")
        if not isinstance(outputs, list) or not outputs:
            raise ValueError("outputs 必须是非空列表，例如 ['H', 'S']")

        return {
            "fluid": fluid,
            "inputs": inputs,
            "outputs": outputs,
        }

    def _convert_input_pair(self, inputs: Dict[str, Any]) -> Tuple[str, float, str, float]:
        """将工程单位输入转换为 SI。"""
        input_items = list(inputs.items())
        in1_name, in1_value = input_items[0]
        in2_name, in2_value = input_items[1]
        if in1_name not in INPUT_KEY_MAP or in2_name not in INPUT_KEY_MAP:
            raise ValueError(
                f"暂不支持的输入参数组合: {in1_name}, {in2_name}。"
                f" 支持参数为 {sorted(INPUT_KEY_MAP.keys())}"
            )
        cp_in1, factor1 = INPUT_KEY_MAP[in1_name]
        cp_in2, factor2 = INPUT_KEY_MAP[in2_name]
        return cp_in1, float(in1_value) * factor1, cp_in2, float(in2_value) * factor2

    def _build_state_metadata(
        self,
        props_si: Callable[..., float],
        fluid: str,
        inputs: Dict[str, Any],
        cp_in1: str,
        cp_value1: float,
        cp_in2: str,
        cp_value2: float,
        raw_results: Dict[str, float],
    ) -> Dict[str, Any]:
        """补充状态说明信息。"""
        metadata: Dict[str, Any] = {
            "phase": None,
            "phase_source": "CoolProp",
            "near_saturation": False,
            "state_pair_independent": True,
            "notes": [],
            "display_overrides": {},
            "raw_results": dict(raw_results),
        }
        notes: List[str] = metadata["notes"]

        try:
            phase_code = int(props_si("Phase", cp_in1, cp_value1, cp_in2, cp_value2, fluid))
            metadata["phase"] = PHASE_LABELS.get(phase_code, f"phase_{phase_code}")
        except Exception:
            metadata["phase"] = None

        if "Q" in raw_results and math.isclose(raw_results["Q"], -1.0, rel_tol=0.0, abs_tol=1e-9):
            metadata["display_overrides"]["Q"] = None
            notes.append("当前状态位于单相区，干度 Q 无定义。")

        if set(inputs.keys()) == {"T", "P"}:
            temperature_k = float(inputs["T"])
            pressure_pa = float(inputs["P"]) * 1000.0
            try:
                saturation_temperature = float(props_si("T", "P", pressure_pa, "Q", 0, fluid))
                saturation_pressure = float(props_si("P", "T", temperature_k, "Q", 0, fluid))
                delta_t = temperature_k - saturation_temperature
                delta_p = pressure_pa - saturation_pressure
                near_saturation = abs(delta_t) <= 0.05 or abs(delta_p) <= 200.0
                metadata["near_saturation"] = near_saturation
                metadata["saturation_reference"] = {
                    "temperature_k": saturation_temperature,
                    "pressure_kpa": saturation_pressure / 1000.0,
                    "delta_temperature_k": delta_t,
                    "delta_pressure_kpa": delta_p / 1000.0,
                }
                if near_saturation:
                    metadata["state_pair_independent"] = False
                    notes.append("当前 T-P 状态点接近饱和线，严格工程语义下不宜简单表述为“两独立状态量唯一确定”。")
                    notes.append("若工质精确位于饱和线，T 与 P 满足饱和关系，仍需结合干度 Q 或相别信息区分饱和液、湿蒸汽或饱和蒸汽。")
            except Exception:
                pass
        return metadata

    def calculate(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """执行流体物性计算。"""
        try:
            normalized = self.normalize_request(request)
            fluid = normalized["fluid"]
            inputs = normalized["inputs"]
            outputs = normalized["outputs"]
            cp_in1, cp_value1, cp_in2, cp_value2 = self._convert_input_pair(inputs)
            props_si = self._props_loader()

            raw_results: Dict[str, float] = {}
            for output_name in outputs:
                if output_name not in OUTPUT_KEY_MAP:
                    raise ValueError(
                        f"暂不支持的输出参数: {output_name}。"
                        f" 支持参数为 {sorted(OUTPUT_KEY_MAP.keys())}"
                    )
                cp_output, factor = OUTPUT_KEY_MAP[output_name]
                raw_value = props_si(cp_output, cp_in1, cp_value1, cp_in2, cp_value2, fluid)
                raw_results[output_name] = float(raw_value) * factor

            metadata = self._build_state_metadata(
                props_si=props_si,
                fluid=fluid,
                inputs=inputs,
                cp_in1=cp_in1,
                cp_value1=cp_value1,
                cp_in2=cp_in2,
                cp_value2=cp_value2,
                raw_results=raw_results,
            )

            display_results: Dict[str, Optional[float]] = dict(raw_results)
            for key, value in metadata.get("display_overrides", {}).items():
                if key in display_results:
                    display_results[key] = value

            return {
                "success": True,
                "results": display_results,
                "metadata": metadata,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "success": False,
                "results": {},
                "metadata": {"notes": []},
                "error": str(exc),
            }

    def structured_search(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """输出兼容检索执行器的结构化结果。"""
        calc_result = self.calculate(request)
        normalized = request if isinstance(request, dict) else {}
        try:
            normalized = self.normalize_request(normalized)
        except Exception:
            normalized = request if isinstance(request, dict) else {}
        query_text = (
            f"fluid={normalized.get('fluid', '')}, "
            f"inputs={normalized.get('inputs', {})}, "
            f"outputs={normalized.get('outputs', [])}"
        )
        return {
            "query": query_text,
            "answer": (
                f"流体物性计算成功: {calc_result['results']}"
                if calc_result["success"]
                else f"流体物性计算失败: {calc_result['error']}"
            ),
            "success": calc_result["success"],
            "results": calc_result["results"],
            "metadata": calc_result.get("metadata", {}),
            "error": calc_result["error"],
            "retrieval_results": [],
        }
