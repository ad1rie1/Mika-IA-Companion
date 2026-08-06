from django.apps import AppConfig


class DrivesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "drives"

    def ready(self):
        # Answering someone relieves the EXPRESSION drive (partially) and
        # counts as activity toward REST. This used to be an inline call in
        # pipeline.processor wrapped in its own try/except: the processor
        # had to know that drives exist, and that an internal trigger must
        # not count. Both are drive policy, so both live here now.
        from pipeline.signals import TURN_COMPLETED
        from utils.eventbus import PRIORITY_OBSERVER, DeliveryMode, event_bus

        async def _on_turn_completed(event) -> None:
            # Internal triggers are excluded: the conscience already calls
            # drive_engine.on_act() for those, and double-counting would
            # empty EXPRESSION on every murmur.
            if event.data.get("intent") == "INTERNAL_TRIGGER":
                return
            from drives.engine import drive_engine
            from identity.trust import is_internal_person
            drive_engine.on_reply(word_count=event.data.get("word_count", 0))

            # Quelqu'un lui a parlé : SOCIAL est comblé, CURIOSITY un peu.
            # La règle vivait dans conscience.observe(), énoncée par une
            # liste littérale de types d'événements — c'était le SEUL
            # appelant de on_conversation(), donc la seule voie
            # d'assouvissement de SOCIAL, et elle dépendait du nom que le
            # canal d'entrée donnait à son événement. Un canal qui n'émet
            # pas exactement ce nom laissait SOCIAL bloqué à 1.0 pendant
            # que la conversation battait son plein. Ici elle suit le tour,
            # quel que soit le canal.
            if not is_internal_person(event.data.get("person_id")):
                drive_engine.on_conversation(from_person=True)

        event_bus.subscribe(
            _on_turn_completed,
            name="drives",
            pattern=TURN_COMPLETED,
            # AWAIT at observer priority: this is an in-RAM mutation that
            # returns immediately, and the thinking delay computed a few
            # lines later in the same turn reads the energy level it feeds.
            # Detaching it would make that read a coin flip.
            mode=DeliveryMode.AWAIT,
            priority=PRIORITY_OBSERVER,
        )
