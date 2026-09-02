"""Le pool de la Forge se répare quand tous ses fils sont épinglés.

Un handler qui passe son temps dans un appel C (regex pathologique,
puissance entière géante) n'est pas interruptible par le traceur : le fil
survit à sa deadline et garde son jeton. Avec deux fils épinglés, l'ancien
``_submit`` attendait un jeton pour toujours — tick, événement, et l'outil
``forge_test_module`` en plein tour de conversation.
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from modules.plugins.forge.module import ForgeModule


def _host(workers: int) -> ForgeModule:
    host = ForgeModule()
    host._loop = asyncio.get_running_loop()
    host._pool_workers = workers
    host._pool_slots = asyncio.Semaphore(workers)
    host._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="forge-test")
    return host


class TestPoolAutoReparation:

    async def test_un_fil_epingle_garde_son_jeton_mais_le_pool_survit(self):
        host = _host(workers=1)
        gate = threading.Event()
        with pytest.raises(asyncio.TimeoutError):
            await host._submit(gate.wait, deadline_s=0.05)

        # Le seul fil est épinglé : le pool est remplacé, pas bloqué.
        assert host._pool_gen == 1
        assert host._pinned == 0
        result, _ = await host._submit(lambda: "ok", deadline_s=1.0)
        assert result == "ok"
        gate.set()
        host._executor.shutdown(wait=True)

    async def test_un_fil_epingle_sur_deux_ne_remplace_pas_le_pool(self):
        host = _host(workers=2)
        gate = threading.Event()
        with pytest.raises(asyncio.TimeoutError):
            await host._submit(gate.wait, deadline_s=0.05)
        assert host._pool_gen == 0
        assert host._pinned == 1
        result, _ = await host._submit(lambda: "encore un fil", deadline_s=1.0)
        assert result == "encore un fil"
        gate.set()
        await asyncio.sleep(0.05)
        # Le fil zombie a fini : il rend son jeton ET son compte d'épinglé.
        assert host._pinned == 0
        host._executor.shutdown(wait=True)

    async def test_le_zombie_qui_finit_apres_remplacement_ne_touche_pas_le_nouveau_pool(self):
        host = _host(workers=1)
        gate = threading.Event()
        with pytest.raises(asyncio.TimeoutError):
            await host._submit(gate.wait, deadline_s=0.05)
        assert host._pool_gen == 1
        # Un nouvel épinglage de la génération 1, pour vérifier que l'ancien
        # zombie ne le décompte pas quand il se termine.
        gate2 = threading.Event()
        with pytest.raises(asyncio.TimeoutError):
            await host._submit(gate2.wait, deadline_s=0.05)
        assert host._pool_gen == 2  # un fil, épinglé → remplacé à nouveau
        gate.set()
        await asyncio.sleep(0.05)
        assert host._pinned == 0 and host._pool_gen == 2
        gate2.set()
        await asyncio.sleep(0.05)
        host._executor.shutdown(wait=True)

    async def test_l_acquisition_du_jeton_est_bornee(self):
        """Un jeton qui ne vient pas est un refus qui dit pourquoi, jamais
        une attente sans fin — sans passer par le remplacement (ici le fil
        n'est pas épinglé, il est simplement occupé)."""
        host = _host(workers=1)
        await host._pool_slots.acquire()  # pool occupé par un tiers
        with pytest.raises(asyncio.TimeoutError, match="aucun fil libre"):
            await host._submit(lambda: "jamais", deadline_s=0.05)
        host._pool_slots.release()
        host._executor.shutdown(wait=True)
