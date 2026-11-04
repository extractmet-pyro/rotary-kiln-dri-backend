"""Exports: JSON, CSV (profiles), XLSX (multi-sheet) and a server-side PDF
shift/scenario report (matplotlib, Agg backend)."""
from __future__ import annotations

import io
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

BRAND = "#0f5c63"


def profiles_frame(res: dict) -> pd.DataFrame:
    p = res["profiles"]
    cols = {k: v for k, v in p.items() if isinstance(v, list) and len(v) == len(p["z_m"]) and not isinstance(v[0], str)}
    df = pd.DataFrame(cols)
    for grp in ("Fe_phase_fraction", "gas_vol_pct_wet", "solids_wt_pct"):
        for k, v in p.get(grp, {}).items():
            df[f"{grp}.{k}"] = v
    df["zone"] = p.get("zone_label")
    return df


def to_csv(res: dict) -> bytes:
    return profiles_frame(res).to_csv(index=False).encode()


def to_xlsx(res: dict) -> bytes:
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as w:
        pd.DataFrame([{"key": k, "value": v} for k, v in res["kpi"].items()]).to_excel(w, sheet_name="KPIs", index=False)
        profiles_frame(res).to_excel(w, sheet_name="Axial profiles", index=False)
        mb = res["material_balance"]
        pd.DataFrame(mb["inputs"]).to_excel(w, sheet_name="Inputs", index=False)
        pd.DataFrame([{k: (json.dumps(v) if isinstance(v, dict) else v) for k, v in r.items()} for r in mb["outputs"]]
                     ).to_excel(w, sheet_name="Outputs", index=False)
        eb = res["elemental_balances"]
        if eb.get("available"):
            pd.DataFrame(eb["elements"]).to_excel(w, sheet_name="Element balance", index=False)
        hb = res["heat_balance"]
        rows = [{"side": "in", "item": k, "kW": v} for k, v in hb["inputs_kW"].items()] + \
               [{"side": "out", "item": k, "kW": v} for k, v in hb["outputs_kW"].items()]
        pd.DataFrame(rows).to_excel(w, sheet_name="Heat balance", index=False)
        pd.DataFrame(res["reaction_summary"]).to_excel(w, sheet_name="Reactions", index=False)
        dri = res["quality"]["dri"]
        pd.DataFrame([{"item": k, "value": v} for k, v in dri.items() if not isinstance(v, dict)]).to_excel(
            w, sheet_name="DRI quality", index=False)
        pd.DataFrame([{"warning": x} for x in res.get("warnings", [])] or [{"warning": "none"}]).to_excel(
            w, sheet_name="Warnings", index=False)
        if res.get("transient"):
            pd.DataFrame(res["transient"]["series"]).to_excel(w, sheet_name="Transient", index=False)
    return bio.getvalue()


def to_pdf(res: dict, title: str = "Rotary-kiln DRI digital twin - scenario report") -> bytes:
    bio = io.BytesIO()
    k = res["kpi"]
    p = res["profiles"]
    z = p["z_m"]
    with PdfPages(bio) as pdf:
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.text(0.07, 0.95, title, fontsize=14, weight="bold", color=BRAND)
        fig.text(0.07, 0.925, f"Plant: {res['plant']['name']}  |  config {res['plant_config_version']}  |  "
                              f"model {res['model_version']}", fontsize=8)
        fig.text(0.07, 0.91, f"Scenario: {res.get('scenario_name','')}   Mode: {res['mode']}   Source: "
                             f"{res['labels']['source']}   Validation: {res['labels']['validation']}", fontsize=8,
                 color="#b03030")
        rows = [("Metallization", f"{k['metallization_pct']:.2f} %"), ("DRI output", f"{k['dri_t_h']:.2f} t/h"),
                ("Total Fe / metallic Fe", f"{k['Fe_total_pct']:.2f} / {k['Fe_metallic_pct']:.2f} %"),
                ("FeO / C / S", f"{k['FeO_pct']:.2f} / {k['C_pct']:.3f} / {k['S_pct']:.3f} %"),
                ("Specific coal", f"{k['coal_kg_per_t_dri']:.0f} kg/t DRI"),
                ("Coal energy", f"{k['coal_energy_GJ_per_t_dri']:.2f} GJ/t DRI"),
                ("Peak bed / gas T", f"{k['peak_bed_T_C']:.0f} / {k['peak_gas_T_C']:.0f} C"),
                ("Exit gas T", f"{k['exit_gas_T_C']:.0f} C"), ("Peak shell T", f"{k['peak_shell_T_C']:.0f} C"),
                ("Residence (pellet transit)", f"{k['residence_time_h']:.2f} h"),
                ("Shell loss", f"{k['shell_loss_kW']:.0f} kW"), ("WHRB steam", f"{k['steam_t_h']:.1f} t/h"),
                ("CO2", f"{k['CO2_t_per_t_dri']:.2f} t/t DRI"),
                ("Accretion risk (proxy)", f"{k['accretion_risk_max']:.2f} ({k['accretion_band']})")]
        y = 0.86
        for a, b in rows:
            fig.text(0.09, y, a, fontsize=10)
            fig.text(0.55, y, b, fontsize=10, weight="bold")
            y -= 0.025
        eb = res["elemental_balances"]
        fig.text(0.07, y - 0.02, "Conservation audit", fontsize=11, weight="bold", color=BRAND)
        y -= 0.045
        if eb.get("available"):
            fig.text(0.09, y, f"mass rel. residual {eb['mass']['relative_residual']:.2e};  energy rel. residual "
                              f"{eb['energy']['relative_residual']:.2e}", fontsize=9)
            y -= 0.02
            for r in eb["elements"][:8]:
                fig.text(0.09, y, f"{r['element']}: in {r['in_kg']:.1f} kg, out {r['out_kg']:.1f} kg, acc "
                                  f"{r['accumulation_kg']:.2f} kg, rel. residual {r['relative_residual']:.1e}", fontsize=8)
                y -= 0.017
        fig.text(0.07, y - 0.02, "Warnings", fontsize=11, weight="bold", color=BRAND)
        y -= 0.045
        for wtxt in (res.get("warnings") or ["none"])[:10]:
            fig.text(0.09, y, "- " + wtxt[:110], fontsize=8)
            y -= 0.017
        fig.text(0.07, 0.03, "Advisory/simulation output. Not a certified control or safety function. "
                             "Extractmet Private Limited.", fontsize=7, color="#555")
        pdf.savefig(fig)
        plt.close(fig)
        fig, ax = plt.subplots(3, 1, figsize=(8.27, 11.69))
        ax[0].plot(z, p["T_gas_C"], label="gas (model)", color="#d1495b")
        ax[0].plot(z, p["T_bed_C"], label="bed (model)", color="#edae49")
        ax[0].plot(z, p["T_wall_hot_face_C"], label="wall hot face (model)", color="#00798c")
        ax[0].plot(z, p["T_shell_C"], label="shell (model)", color="#30638e")
        ax[0].set_ylabel("Temperature, C")
        ax[0].legend(fontsize=8)
        ax[0].set_title("Axial temperatures (z = 0 feed end)")
        ff = p["Fe_phase_fraction"]
        ax[1].stackplot(z, ff["Fe2O3"], ff["Fe3O4"], ff["FeO"], ff["Fe"], labels=["Fe2O3", "Fe3O4", "FeO", "Fe"],
                        colors=["#8c2d04", "#555555", "#cc8b3c", "#7a9e9f"])
        ax[1].set_ylabel("Fraction of Fe")
        ax[1].legend(fontsize=8, loc="center left")
        ax[1].set_title("Iron phase distribution")
        g = p["gas_vol_pct_dry"]
        for sp, c in (("CO", "#d1495b"), ("CO2", "#30638e"), ("O2", "#00798c")):
            ax[2].plot(z, g[sp], label=sp, color=c)
        ax[2].set_xlabel("z, m")
        ax[2].set_ylabel("vol % dry")
        ax[2].legend(fontsize=8)
        ax[2].set_title("Freeboard gas composition (model-estimated)")
        fig.tight_layout()
        pdf.savefig(fig)
        plt.close(fig)
        hb = res["heat_balance"]
        fig, ax = plt.subplots(figsize=(8.27, 6))
        items = list(hb["outputs_kW"].items())
        ax.barh([a for a, _ in items], [b for _, b in items], color=BRAND)
        ax.set_xlabel("kW")
        ax.set_title(f"Energy ledger outputs (in {hb['total_in_kW']:.0f} kW; residual {hb['residual_kW']:.1f} kW)")
        fig.tight_layout()
        pdf.savefig(fig)
        plt.close(fig)
        if res.get("transient"):
            s = pd.DataFrame(res["transient"]["series"])
            fig, ax = plt.subplots(3, 1, figsize=(8.27, 11.69))
            ax[0].plot(s["t_h"], s["metallization_discharge_pct"], color=BRAND)
            ax[0].set_ylabel("Metallization, %")
            ax[1].plot(s["t_h"], s["peak_bed_T_C"], color="#edae49", label="peak bed")
            ax[1].plot(s["t_h"], s["exit_gas_T_C"], color="#d1495b", label="exit gas")
            ax[1].legend()
            ax[2].plot(s["t_h"], s["dri_t_h"], color="#30638e")
            ax[2].set_ylabel("DRI t/h")
            ax[2].set_xlabel("time, h")
            fig.tight_layout()
            pdf.savefig(fig)
            plt.close(fig)
    return bio.getvalue()
