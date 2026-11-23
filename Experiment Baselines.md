
# I. Scenario set: L3-mini

## 1. Deepseek-flash

### **"thinking": "disabled"**
1. [B](validation_runs/l3_deepseek_B_thor_BG_QaasC1/deepseek_b)
2. [B+P](validation_runs/deepseek_flash_BP_true_rjvv0K/l3)
3. [B+G(structured-knowledge/v1)](validation_runs/l3_mini20_deepseek_flash_BG_nothink_duHPzu)
4. [B+Original-l2_textsim_grouped_differ, UNDONE]()
5. [detail=true, UNDONE]()


## 2. Thor Qwen 35B 

### **"enable_thinking": false**
1. [B](validation_runs/l3_mini20_qwen36_35b_structured_b_on_nothink_DkOhBQ)
2. [B+P](validation_runs/l3_mini20_qwen36_35b_structured_p_on_nothink_E7vlwd)
3. [B+G(structured-knowledge/v1)](validation_runs/l3_deepseek_B_thor_BG_QaasC1/thor_qwen35b_bg)
4. [B+Original-l2_textsim_grouped_differ, UNDONE]()
5. [detail=true, UNDONE]()


# II. Scenario set: L3-full

## 1. Thor Qwen 35B

### **"enable_thinking": false**
1. [B+P, 64/90](validation_runs/l3_formal90_thor_qwen35b_BP_nothink_lvxtsU)
2. [B+P, reruns](validation_runs/l3_formal90_thor_qwen35b_BP_nothink_rerun_BvciC0)
3. [B, 61/90](validation_runs/l3_formal90_thor_qwen35b_B_nothink_vrNWR4)
4. [B, reruns, UNDONE]()

## 2. Deepseek-flash

### **"thinking": "disabled"**
1. [B+P, 73/90](validation_runs/l3_formal90_deepseek_flash_BP_nothink_OL0lel)
2. [B+P, reruns](validation_runs/l3_formal90_deepseek_flash_BP_nothink_rerun_qn7CQM)
3. [B](validation_runs/l3_formal90_deepseek_flash_B_nothink_El08gq)

